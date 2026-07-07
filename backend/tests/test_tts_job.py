"""ASYNC-AI-3 / TTSJOB-2 — coverage of the TTS background job sync-client
coupling AND the persisted job lifecycle.

``_run_tts_job`` (routes_ai.py) runs in a ``threading.Thread`` OFF the event loop.
After ASYNC-AI-1, ``svc.client`` is ``AsyncOpenAI`` and must NOT be used there; the
job must use ``svc.sync_client`` (synchronous ``OpenAI``) for the summary/explanation
LLM step. This module proves:

* The job reaches ``status == 'done'`` for ``audio_type`` ∈ {summary, explanation,
  podcast}, persists the row in ``tts_jobs`` (TTSJOB-2) with ``audio_url``, writes
  ``contents.audio_url``/``audio_type`` (POD-6), and raises NO await/coroutine error.
* It calls the SYNC client (recorded on the fake), never the async client.
* Regression guard: if the job were (wrongly) handed an AsyncOpenAI for the LLM
  step, its synchronous ``.create(...)`` returns a coroutine and the summary path
  fails — demonstrating exactly why the sync client is required.

Headless: ElevenLabs, OpenAI and Supabase are all faked/monkeypatched. No network.
"""
from __future__ import annotations

import sys
import types

import pytest

import routes_ai
from fakes import FakeAsyncOpenAI, FakeSupabaseClient, FakeSyncOpenAI, _FakeChatCompletion
from repositories.tts_job_repo import TtsJobRepository
from services.ai_service import AIService

USER_ID = "user-1"


# ---------------------------------------------------------------------------
# Fake for ElevenLabs, installed via monkeypatch. Supabase persistence uses
# the shared ``FakeSupabaseClient`` (tests/fakes.py) so both the ``tts_jobs``
# lifecycle row AND ``contents.audio_url``/``audio_type`` land in the same
# in-memory store the test can assert on.
# ---------------------------------------------------------------------------

class _FakeTTS:
    def convert(self, **kwargs):
        # Real SDK returns a generator of audio chunks; mirror that so the
        # production ``b"".join(...)`` works unchanged.
        yield b"FAKE"
        yield b"MP3"


class _FakeElevenLabs:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.text_to_speech = _FakeTTS()


@pytest.fixture
def tts_env(monkeypatch, tmp_path):
    """Wire up a headless environment for ``_run_tts_job``.

    Returns (svc, fake_sync, fake_async, sb, upload_dir). ``sb`` is the SAME
    ``FakeSupabaseClient`` instance the job recreates via the patched
    ``create_client`` — both ``tts_jobs`` and ``contents`` mutations land here.
    """
    fake_sync = FakeSyncOpenAI(response_text="Resumo gerado pelo cliente sync.")
    fake_async = FakeAsyncOpenAI(response_text='{"unused": true}')
    svc = AIService(client=fake_async, sync_client=fake_sync)

    monkeypatch.setattr(routes_ai, "get_ai_service", lambda: svc)
    monkeypatch.setattr(routes_ai, "ELEVENLABS_API_KEY", "fake-key", raising=False)

    # Patch the ElevenLabs client the job imports as ``from elevenlabs.client import ...``.
    el_mod = types.ModuleType("elevenlabs.client")
    el_mod.ElevenLabs = _FakeElevenLabs
    monkeypatch.setitem(sys.modules, "elevenlabs.client", el_mod)

    # Patch supabase.create_client used for lifecycle + audio_url persistence.
    sb = FakeSupabaseClient({"tts_jobs": [], "contents": [{"id": "content-1", "body": "seed"}]})
    supabase_mod = sys.modules.get("supabase") or types.ModuleType("supabase")
    monkeypatch.setattr(supabase_mod, "create_client", lambda url, key: sb, raising=False)
    monkeypatch.setitem(sys.modules, "supabase", supabase_mod)

    return svc, fake_sync, fake_async, sb, str(tmp_path)


def _run(job_id, audio_type, upload_dir, sb, content_id="content-1"):
    # TTSJOB-2: the job row must exist BEFORE ``_run_tts_job`` runs (the route
    # seeds it via ``TtsJobRepository.seed_processing`` before dispatching the
    # thread) — mirror that here so ``mark_done``/``mark_error`` have a row to
    # transition.
    TtsJobRepository(sb).seed_processing(job_id, content_id, USER_ID, audio_type)
    routes_ai._run_tts_job(
        job_id=job_id,
        content_id=content_id,
        content_text="Conteudo academico longo para sintetizar em audio.",
        audio_type=audio_type,
        voice_id="21m00Tcm4TlvDq8ikWAM",
        upload_dir=upload_dir,
        supabase_url="http://fake",
        supabase_key="fake-key",
        user_id=USER_ID,
    )
    return TtsJobRepository(sb).get_by_id(job_id)


def test_summary_job_uses_sync_client_and_reaches_done(tts_env):
    svc, fake_sync, fake_async, sb, upload_dir = tts_env

    job = _run("job-summary", "summary", upload_dir, sb)

    assert job["status"] == "done", job
    assert job["audio_url"].startswith("/uploads/tts/")
    # The summary LLM step used the SYNC client...
    assert len(fake_sync.calls) == 1
    # ...and never the async client (which would have leaked a coroutine).
    assert len(fake_async.calls) == 0
    # audio_url + audio_type were persisted to contents (POD-6).
    content = sb.find("contents", id="content-1")
    assert content["audio_url"] == job["audio_url"]
    assert content["audio_type"] == "summary"


def test_explanation_job_uses_sync_client_and_reaches_done(tts_env):
    svc, fake_sync, fake_async, sb, upload_dir = tts_env

    job = _run("job-explanation", "explanation", upload_dir, sb)

    assert job["status"] == "done", job
    assert job["audio_url"].startswith("/uploads/tts/")
    assert len(fake_sync.calls) == 1
    assert len(fake_async.calls) == 0


def test_podcast_job_skips_llm_and_reaches_done(tts_env):
    """``podcast`` does no LLM step — straight to TTS. Must still reach 'done'."""
    svc, fake_sync, fake_async, sb, upload_dir = tts_env

    job = _run("job-podcast", "podcast", upload_dir, sb)

    assert job["status"] == "done", job
    assert job["audio_url"].startswith("/uploads/tts/")
    # No summary/explanation LLM call for podcast.
    assert len(fake_sync.calls) == 0
    assert len(fake_async.calls) == 0


def test_async_client_in_thread_would_break_summary_REGRESSION(monkeypatch, tts_env):
    """REGRESSION PROOF: handing the job an AsyncOpenAI for the LLM step breaks it.

    This is the exact silent-failure ASYNC-AI-1 guards against (QA item #1): calling
    the async client's ``.create(...)`` synchronously returns a coroutine, not a
    completion, so ``result.choices[0]`` blows up and the job lands in 'error'. We
    simulate the misconfiguration by giving the service an AsyncOpenAI as its
    ``sync_client`` and assert the job does NOT silently produce audio.
    """
    _, _, fake_async, sb, upload_dir = tts_env

    # Misconfigure: sync_client is actually async (the bug).
    broken_svc = AIService(client=fake_async, sync_client=FakeAsyncOpenAI())
    monkeypatch.setattr(routes_ai, "get_ai_service", lambda: broken_svc)

    job = _run("job-broken", "summary", upload_dir, sb)

    # The job must surface an error, not pretend success — proving the coupling matters.
    assert job["status"] == "error", job
    assert job.get("error")


# ===========================================================================
# TTSJOB-2 — persisted lifecycle: non-destructive status, no phantom-done.
# ===========================================================================


class TestPersistedLifecycle:
    def test_status_read_is_non_destructive_two_polls_match(self, tts_env):
        """#58: audio_job_status must NOT pop; two consecutive reads after
        `done` return the same payload (proven here at the repo layer that
        backs the route)."""
        svc, fake_sync, fake_async, sb, upload_dir = tts_env
        job = _run("job-poll", "summary", upload_dir, sb)
        assert job["status"] == "done"

        repo = TtsJobRepository(sb)
        first = repo.get_by_id("job-poll")
        second = repo.get_by_id("job-poll")
        assert first is not None and second is not None
        assert first["status"] == second["status"] == "done"
        assert first["audio_url"] == second["audio_url"]

    def test_persist_failure_after_synthesis_marks_error_not_done(self, tts_env, monkeypatch):
        """#34/#35: if the contents.audio_url UPDATE never lands (even after
        retries), the job must surface `error` — never a phantom `done`
        pointing at audio the read path can never find again."""
        svc, fake_sync, fake_async, sb, upload_dir = tts_env

        monkeypatch.setattr(routes_ai, "_persist_audio_url_with_retry", lambda *a, **k: False)

        job = _run("job-phantom", "summary", upload_dir, sb)

        assert job["status"] == "error", job
        assert "persistir" in (job.get("error") or "").lower()

    def test_job_row_carries_owning_user_id(self, tts_env):
        """The persisted row carries ``user_id`` so the route layer
        (``audio_job_status``) can enforce ownership (cross-user -> 404)."""
        svc, fake_sync, fake_async, sb, upload_dir = tts_env
        job = _run("job-owner", "summary", upload_dir, sb)
        assert job["user_id"] == USER_ID
