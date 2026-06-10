"""TKN-5 — the TTS pipeline meters LLM + ElevenLabs spend and pre-checks budget.

Bug #12: the two paid AI steps of audio generation — (1) the LLM that writes the
script (summary/explanation) and (2) the ElevenLabs voice synthesis — never touched
the spend ledger, the initiator's ``user_id`` was not propagated into the worker
thread, there was no budget pre-check before the (paid) thread started, and the
broad final ``except`` in ``_run_tts_job`` swallowed every tracking failure.

TKN-5 closes all of that. This module is the fail-before / pass-after oracle of
each AC:

* (a) a SUCCESSFUL job increments the daily ledger with the LLM token cost AND
      (feature flag ON) the ElevenLabs char-equivalent, both charged to the
      INITIATOR captured at enqueue time;
* (b) a user OVER the daily cap is barred at the route-level pre-check BEFORE the
      thread is dispatched — no thread, no ElevenLabs call, HTTP 503;
* (c) a tracking failure is LOGGED at ERROR with stage context (provider/user/
      content) and does NOT mask the happy path (the job still reaches 'done');
* (d) feature flag OFF → only the LLM is tracked, ElevenLabs is omitted.

Design notes
------------
* The ledger column is a single ``tokens_used`` int with no provider dimension
  (KISS — no schema change). The ElevenLabs char-equivalent (``len(tts_input)``)
  is summed into the SAME counter; the provider ('llm' vs 'elevenlabs') is
  disambiguated only in the structured log, which (c) asserts on directly.
* Inside the worker thread the request-scoped ``get_supabase`` dependency is
  unavailable, so the job recreates a SYNC Supabase client from the
  ``supabase_url``/``supabase_key`` it is handed. Here that ``create_client`` is
  monkeypatched to return an in-process :class:`FakeSupabaseClient` (rpc enabled),
  which IS the ledger we then assert on.

Headless: ElevenLabs, OpenAI and Supabase are all faked/monkeypatched. No network.
"""
from __future__ import annotations

import logging
import sys
import types

import pytest

import routes_ai
from conftest import TEACHER_ID, STUDENT_A_ID
from fakes import FakeAsyncOpenAI, FakeSyncOpenAI, FakeSupabaseClient
from repositories.token_usage_repo import TokenUsageRepository
from services.ai_service import AIService

# Each fake chat completion = 10 + 20 tokens (see tests/fakes.py::_FakeUsage).
FAKE_LLM_TOKENS = 30
# FakeSyncOpenAI default summary content — drives both ``tts_input`` and the
# ElevenLabs char-equivalent (len of the truncated summary).
FAKE_SUMMARY = "summarized content"


# ---------------------------------------------------------------------------
# Fakes for ElevenLabs (records whether synthesis ran) + a settings stub.
# ---------------------------------------------------------------------------
class _FakeTTS:
    def __init__(self, recorder):
        self._recorder = recorder

    def convert(self, **kwargs):
        # Real SDK returns a generator of audio chunks; mirror that so the
        # production ``b"".join(...)`` works unchanged.
        self._recorder.append(kwargs)
        yield b"FAKE"
        yield b"MP3"


class _FakeElevenLabs:
    calls: list = []

    def __init__(self, api_key=None):
        self.api_key = api_key
        self.text_to_speech = _FakeTTS(_FakeElevenLabs.calls)


def _settings_stub(*, elevenlabs_tracking: bool):
    """A get_settings() stand-in toggling only the ElevenLabs tracking flag."""
    return types.SimpleNamespace(ENABLE_ELEVENLABS_COST_TRACKING=elevenlabs_tracking)


@pytest.fixture
def job_env(monkeypatch, tmp_path):
    """Headless environment for invoking ``_run_tts_job`` directly.

    Returns (svc, ledger, upload_dir). ``ledger`` is the FakeSupabaseClient the
    worker recreates via the patched ``create_client`` — the same object the job's
    ``track_token_usage`` writes to, so the test can assert the ledger after.
    """
    fake_sync = FakeSyncOpenAI(response_text=FAKE_SUMMARY)
    fake_async = FakeAsyncOpenAI(response_text='{"unused": true}')
    svc = AIService(client=fake_async, sync_client=fake_sync)
    monkeypatch.setattr(routes_ai, "get_ai_service", lambda: svc)
    monkeypatch.setattr(routes_ai, "ELEVENLABS_API_KEY", "fake-key", raising=False)

    # ElevenLabs client the job imports as ``from elevenlabs.client import ...``.
    _FakeElevenLabs.calls = []
    el_mod = types.ModuleType("elevenlabs.client")
    el_mod.ElevenLabs = _FakeElevenLabs
    monkeypatch.setitem(sys.modules, "elevenlabs.client", el_mod)

    # The worker recreates a Supabase client via ``from supabase import create_client``.
    # Hand it an in-process fake WITH the increment_token_usage RPC = our ledger.
    ledger = FakeSupabaseClient({"token_usage": [], "contents": []}, rpc_enabled=True)
    supabase_mod = sys.modules.get("supabase") or types.ModuleType("supabase")
    monkeypatch.setattr(supabase_mod, "create_client", lambda url, key: ledger, raising=False)
    monkeypatch.setitem(sys.modules, "supabase", supabase_mod)

    monkeypatch.setattr(routes_ai, "_tts_jobs", {}, raising=False)
    return svc, ledger, str(tmp_path)


def _run_job(upload_dir, *, user_id, audio_type="summary", content_id="content-1"):
    routes_ai._run_tts_job(
        job_id=f"job-{audio_type}",
        content_id=content_id,
        content_text="Conteudo academico longo para sintetizar em audio.",
        audio_type=audio_type,
        voice_id="21m00Tcm4TlvDq8ikWAM",
        upload_dir=upload_dir,
        supabase_url="http://fake",
        supabase_key="fake-key",
        user_id=user_id,
    )
    return routes_ai._tts_jobs[f"job-{audio_type}"]


# ===========================================================================
# (a) Successful job — LLM + (flag ON) ElevenLabs charged to the INITIATOR
# ===========================================================================
class TestSuccessfulJobTracksBothProviders:
    def test_llm_and_elevenlabs_charged_to_initiator_with_flag_on(self, job_env, monkeypatch):
        svc, ledger, upload_dir = job_env
        monkeypatch.setattr(routes_ai, "get_settings", lambda: _settings_stub(elevenlabs_tracking=True))

        job = _run_job(upload_dir, user_id=TEACHER_ID, audio_type="summary")

        assert job["status"] == "done", job
        # LLM (script) was charged AND the ElevenLabs char-equivalent (len of the
        # truncated summary text) was summed into the SAME daily counter.
        el_chars = len(FAKE_SUMMARY[:5000])
        expected = FAKE_LLM_TOKENS + el_chars
        assert TokenUsageRepository(ledger).get_today_usage(TEACHER_ID) == expected
        # Charged to the INITIATOR only — nobody else.
        assert TokenUsageRepository(ledger).get_today_usage(STUDENT_A_ID) == 0
        # The synthesis actually ran (one ElevenLabs convert call).
        assert len(_FakeElevenLabs.calls) == 1

    def test_two_jobs_accumulate_into_single_daily_row(self, job_env, monkeypatch):
        """Atomic increments via the RPC — concurrent-safe, one row, no loss."""
        svc, ledger, upload_dir = job_env
        monkeypatch.setattr(routes_ai, "get_settings", lambda: _settings_stub(elevenlabs_tracking=True))

        _run_job(upload_dir, user_id=TEACHER_ID, audio_type="summary")
        _run_job(upload_dir, user_id=TEACHER_ID, audio_type="explanation")

        per_job = FAKE_LLM_TOKENS + len(FAKE_SUMMARY[:5000])
        assert TokenUsageRepository(ledger).get_today_usage(TEACHER_ID) == 2 * per_job
        rows = [r for r in ledger.rows("token_usage") if str(r["user_id"]) == TEACHER_ID]
        assert len(rows) == 1


# ===========================================================================
# (d) Feature flag OFF — only the LLM is tracked, ElevenLabs is omitted
# ===========================================================================
class TestFeatureFlagOffTracksOnlyLLM:
    def test_flag_off_charges_llm_only(self, job_env, monkeypatch):
        svc, ledger, upload_dir = job_env
        monkeypatch.setattr(routes_ai, "get_settings", lambda: _settings_stub(elevenlabs_tracking=False))

        job = _run_job(upload_dir, user_id=TEACHER_ID, audio_type="summary")

        assert job["status"] == "done", job
        # ONLY the LLM cost — the ElevenLabs char-equivalent is NOT added.
        assert TokenUsageRepository(ledger).get_today_usage(TEACHER_ID) == FAKE_LLM_TOKENS
        # Synthesis still ran (audio is still produced); only its tracking is gated.
        assert len(_FakeElevenLabs.calls) == 1

    def test_podcast_flag_off_tracks_nothing(self, job_env, monkeypatch):
        """``podcast`` does no LLM step; with the flag OFF there is nothing to bill."""
        svc, ledger, upload_dir = job_env
        monkeypatch.setattr(routes_ai, "get_settings", lambda: _settings_stub(elevenlabs_tracking=False))

        job = _run_job(upload_dir, user_id=TEACHER_ID, audio_type="podcast")

        assert job["status"] == "done", job
        assert TokenUsageRepository(ledger).get_today_usage(TEACHER_ID) == 0


# ===========================================================================
# (c) Tracking failure is LOGGED with context, NOT swallowed — happy path intact
# ===========================================================================
class TestTrackingFailureLoggedNotSwallowed:
    def test_llm_tracking_failure_logged_and_audio_still_produced(self, job_env, monkeypatch, caplog):
        svc, ledger, upload_dir = job_env
        monkeypatch.setattr(routes_ai, "get_settings", lambda: _settings_stub(elevenlabs_tracking=True))

        # Make the unified tracker blow up — the OLD code's broad ``except`` would
        # have buried this; TKN-5 must log it at ERROR with stage context and keep
        # the happy path (the job still finishes and writes audio).
        def _boom(user_id, tokens, db=None):
            raise RuntimeError("ledger write exploded")

        monkeypatch.setattr(svc, "track_token_usage", _boom)

        with caplog.at_level(logging.ERROR, logger=routes_ai.logger.name):
            job = _run_job(upload_dir, user_id=TEACHER_ID, audio_type="summary", content_id="content-7")

        # Happy path is NOT masked — audio was produced despite the tracking failure.
        assert job["status"] == "done", job
        assert job["audio_url"].startswith("/uploads/tts/")

        # The failure was LOGGED at ERROR with full stage context (provider, user,
        # content), never silently swallowed.
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "tracking failure must be logged at ERROR, not swallowed"
        joined = "\n".join(r.getMessage() for r in errors)
        assert "tracking FAILED" in joined
        assert "provider=llm" in joined
        assert TEACHER_ID in joined
        assert "content-7" in joined

    def test_elevenlabs_tracking_failure_labels_elevenlabs_provider(self, job_env, monkeypatch, caplog):
        """The ElevenLabs-stage failure must be labeled provider=elevenlabs in the log
        (the only place the provider is disambiguated — there is no schema column)."""
        svc, ledger, upload_dir = job_env
        monkeypatch.setattr(routes_ai, "get_settings", lambda: _settings_stub(elevenlabs_tracking=True))

        # Fail ONLY on the ElevenLabs increment (the char-equivalent one). The LLM
        # increment (30 tokens) succeeds; the ElevenLabs one raises and is logged.
        real_track = svc.track_token_usage

        def _selective(user_id, tokens, db=None):
            if tokens == len(FAKE_SUMMARY[:5000]):  # the ElevenLabs char-equivalent
                raise RuntimeError("elevenlabs ledger write exploded")
            return real_track(user_id, tokens, db)

        monkeypatch.setattr(svc, "track_token_usage", _selective)

        with caplog.at_level(logging.ERROR, logger=routes_ai.logger.name):
            job = _run_job(upload_dir, user_id=TEACHER_ID, audio_type="summary")

        assert job["status"] == "done", job
        # LLM still charged; ElevenLabs charge was lost but LOGGED, not swallowed.
        assert TokenUsageRepository(ledger).get_today_usage(TEACHER_ID) == FAKE_LLM_TOKENS
        joined = "\n".join(r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR)
        assert "provider=elevenlabs" in joined


# ===========================================================================
# (b) Budget pre-check — over-cap user is BARRED before any synthesis runs (503)
# ===========================================================================
class TestPreCheckBarsOverBudgetBeforeSynthesis:
    def _inject_over_cap_service(self, monkeypatch, fake_supabase):
        """Wire routes_ai with an AIService whose budget is already at the cap for
        the authenticated teacher (route reads PERSISTED usage via the fake)."""
        fake_async = FakeAsyncOpenAI(response_text='{"x": 1}')
        fake_sync = FakeSyncOpenAI(response_text=FAKE_SUMMARY)
        svc = AIService(client=fake_async, sync_client=fake_sync)
        # Persist the teacher AT the daily cap so the pre-check raises.
        fake_supabase.rpc = fake_supabase._rpc_entry  # type: ignore[attr-defined]
        fake_supabase._rpc_enabled = True
        fake_supabase.seed("token_usage", [])
        svc.track_token_usage(TEACHER_ID, svc.daily_token_limit, fake_supabase)
        monkeypatch.setattr(routes_ai, "get_ai_service", lambda: svc)
        return svc

    def test_over_cap_returns_503_and_starts_no_thread(
        self, client, as_teacher, fake_supabase, monkeypatch
    ):
        # Content the route reads before dispatching.
        fake_supabase.seed("contents", [
            {"id": "content-1", "body": "Conteudo academico para audio."}
        ])
        # ElevenLabs IS configured — so a 503 here can ONLY come from the budget
        # pre-check, never from the missing-key guard.
        monkeypatch.setattr(routes_ai, "ELEVENLABS_API_KEY", "fake-key", raising=False)
        self._inject_over_cap_service(monkeypatch, fake_supabase)

        # Guard: if a thread WERE (wrongly) dispatched, this would explode loudly.
        _FakeElevenLabs.calls = []
        el_mod = types.ModuleType("elevenlabs.client")
        el_mod.ElevenLabs = _FakeElevenLabs
        monkeypatch.setitem(sys.modules, "elevenlabs.client", el_mod)

        def _no_thread(*a, **k):
            raise AssertionError("pre-check must bar the over-cap user BEFORE the thread")

        monkeypatch.setattr(routes_ai, "_run_tts_job", _no_thread)

        resp = client.post(
            "/api/ai/audio/generate-from-content",
            json={"content_id": "content-1", "audio_type": "summary"},
        )

        assert resp.status_code == 503, resp.text
        # No paid synthesis ran — the over-cap user never reached ElevenLabs.
        assert _FakeElevenLabs.calls == []

    def test_within_cap_dispatches_thread(
        self, client, as_teacher, fake_supabase, monkeypatch
    ):
        """Mirror oracle: a teacher WITHIN budget passes the pre-check and the job
        IS dispatched (proving the pre-check gates only over-cap users)."""
        fake_supabase.seed("contents", [
            {"id": "content-1", "body": "Conteudo academico para audio."}
        ])
        monkeypatch.setattr(routes_ai, "ELEVENLABS_API_KEY", "fake-key", raising=False)
        fake_async = FakeAsyncOpenAI(response_text='{"x": 1}')
        svc = AIService(client=fake_async, sync_client=FakeSyncOpenAI(response_text=FAKE_SUMMARY))
        fake_supabase.rpc = fake_supabase._rpc_entry  # type: ignore[attr-defined]
        fake_supabase._rpc_enabled = True
        fake_supabase.seed("token_usage", [])  # no usage → within cap
        monkeypatch.setattr(routes_ai, "get_ai_service", lambda: svc)

        dispatched = {}

        def _capture(*args, **kwargs):
            # ``user_id`` is the LAST positional arg the handler appends to args.
            dispatched["user_id"] = kwargs.get("user_id", args[-1] if args else None)

        monkeypatch.setattr(routes_ai, "_run_tts_job", _capture)

        # Run the dispatched target SYNCHRONOUSLY so the assertion is deterministic
        # (no race with a real background thread).
        import threading as _threading

        class _SyncThread:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None):
                self._target, self._args, self._kwargs = target, args, kwargs or {}

            def start(self):
                if self._target:
                    self._target(*self._args, **self._kwargs)

        monkeypatch.setattr(_threading, "Thread", _SyncThread)

        resp = client.post(
            "/api/ai/audio/generate-from-content",
            json={"content_id": "content-1", "audio_type": "summary"},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "processing"
        # The INITIATOR (authenticated teacher) was propagated to the worker.
        assert dispatched.get("user_id") == TEACHER_ID
