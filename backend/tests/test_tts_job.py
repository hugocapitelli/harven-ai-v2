"""ASYNC-AI-3 — coverage of the TTS background job sync-client coupling.

``_run_tts_job`` (routes_ai.py) runs in a ``threading.Thread`` OFF the event loop.
After ASYNC-AI-1, ``svc.client`` is ``AsyncOpenAI`` and must NOT be used there; the
job must use ``svc.sync_client`` (synchronous ``OpenAI``) for the summary/explanation
LLM step. This module proves:

* The job reaches ``status == 'done'`` for ``audio_type`` ∈ {summary, explanation,
  podcast}, writes ``contents.audio_url``, and raises NO await/coroutine error.
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
from fakes import FakeAsyncOpenAI, FakeSyncOpenAI, _FakeChatCompletion
from services.ai_service import AIService


# ---------------------------------------------------------------------------
# Fakes for ElevenLabs + Supabase, installed via monkeypatch.
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


class _FakeSBTable:
    def __init__(self, store):
        self._store = store
        self._payload = None

    def update(self, payload):
        self._payload = payload
        return self

    def eq(self, col, val):
        self._store.append({"col": col, "val": val, "payload": self._payload})
        return self

    def execute(self):
        return types.SimpleNamespace(data=list(self._store))


class _FakeSB:
    def __init__(self):
        self.writes = []

    def table(self, name):
        return _FakeSBTable(self.writes)


@pytest.fixture
def tts_env(monkeypatch, tmp_path):
    """Wire up a headless environment for ``_run_tts_job``.

    Returns (svc, fake_sync, fake_async, sb, upload_dir).
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

    # Patch supabase.create_client used for audio_url persistence.
    sb = _FakeSB()
    supabase_mod = sys.modules.get("supabase") or types.ModuleType("supabase")
    monkeypatch.setattr(supabase_mod, "create_client", lambda url, key: sb, raising=False)
    monkeypatch.setitem(sys.modules, "supabase", supabase_mod)

    # Isolate the job store between tests.
    monkeypatch.setattr(routes_ai, "_tts_jobs", {}, raising=False)

    return svc, fake_sync, fake_async, sb, str(tmp_path)


def _run(job_id, audio_type, upload_dir, content_id="content-1"):
    routes_ai._run_tts_job(
        job_id=job_id,
        content_id=content_id,
        content_text="Conteudo academico longo para sintetizar em audio.",
        audio_type=audio_type,
        voice_id="21m00Tcm4TlvDq8ikWAM",
        upload_dir=upload_dir,
        supabase_url="http://fake",
        supabase_key="fake-key",
    )
    return routes_ai._tts_jobs[job_id]


def test_summary_job_uses_sync_client_and_reaches_done(tts_env):
    svc, fake_sync, fake_async, sb, upload_dir = tts_env

    job = _run("job-summary", "summary", upload_dir)

    assert job["status"] == "done", job
    assert job["audio_url"].startswith("/uploads/tts/")
    assert job["size_bytes"] > 0
    # The summary LLM step used the SYNC client...
    assert len(fake_sync.calls) == 1
    # ...and never the async client (which would have leaked a coroutine).
    assert len(fake_async.calls) == 0
    # audio_url was persisted to contents.
    assert any(w["payload"].get("audio_url") == job["audio_url"] for w in sb.writes)


def test_explanation_job_uses_sync_client_and_reaches_done(tts_env):
    svc, fake_sync, fake_async, sb, upload_dir = tts_env

    job = _run("job-explanation", "explanation", upload_dir)

    assert job["status"] == "done", job
    assert job["audio_url"].startswith("/uploads/tts/")
    assert len(fake_sync.calls) == 1
    assert len(fake_async.calls) == 0


def test_podcast_job_skips_llm_and_reaches_done(tts_env):
    """``podcast`` does no LLM step — straight to TTS. Must still reach 'done'."""
    svc, fake_sync, fake_async, sb, upload_dir = tts_env

    job = _run("job-podcast", "podcast", upload_dir)

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

    job = _run("job-broken", "summary", upload_dir)

    # The job must surface an error, not pretend success — proving the coupling matters.
    assert job["status"] == "error", job
