"""TTSJOB-2/POD-4/POD-2 — route-level lifecycle: dedup, concurrency cap,
ownership (IDOR), non-destructive/idempotent polling, per-job timeout, and
chunk-and-concatenate for narration longer than one TTS call.

Complements ``test_tts_job.py`` (worker-level: sync-client coupling,
persistence-authority, phantom-done) and ``test_tts_budget.py`` (ledger/
pre-check). This module drives the FastAPI routes directly
(``POST /api/ai/audio/generate-from-content`` +
``GET /api/ai/audio/status/{job_id}``) against the shared ``fake_supabase``
fixture, with the background thread short-circuited to run synchronously so
assertions are deterministic (no real threading/timing race).

Headless: no network, no real Supabase/ElevenLabs/OpenAI.
"""
from __future__ import annotations

import threading as _threading
import time
import types

import pytest

import routes_ai
from conftest import DISCIPLINE_ID, STUDENT_A_ID, STUDENT_B_ID, TEACHER_ID
from fakes import FakeAsyncOpenAI, FakeSyncOpenAI
from repositories.tts_job_repo import TtsJobRepository
from services.ai_service import AIService

# SEC-SCOPE-9: the audio route now enforces cross-teacher ownership on the
# content_id (a TEACHER may only synthesize their OWN content). These tests act
# as TEACHER_ID, who owns DISCIPLINE_ID (conftest seed). Link every content the
# tests read into that discipline's tree so the owning teacher legitimately
# passes the gate — the fix is to complete the fixture chain, never to weaken the
# gate.
_LIFECYCLE_COURSE = "course-tts-lifecycle"
_LIFECYCLE_CHAPTER = "chapter-tts-lifecycle"


def _seed_owned_course_chapter(fake):
    """Seed the course->chapter under TEACHER_ID's owned discipline.

    Content rows are seeded with ``chapter_id=_LIFECYCLE_CHAPTER`` so the ownership
    walk (content -> chapter -> course -> discipline_teachers) resolves to
    TEACHER_ID and the owning teacher passes the SEC-SCOPE-9 gate.
    """
    fake.add("courses", {"id": _LIFECYCLE_COURSE, "title": "Curso TTS",
                         "discipline_id": DISCIPLINE_ID, "status": "active"})
    fake.add("chapters", {"id": _LIFECYCLE_CHAPTER, "course_id": _LIFECYCLE_COURSE,
                         "title": "Cap TTS", "order": 1})


class _SyncThread:
    """``threading.Thread`` stand-in that runs the target INLINE on ``start()``,
    so dispatched TTS jobs are deterministic in tests (no race with a real
    background thread)."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target, self._args, self._kwargs = target, args, kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)

    def join(self, timeout=None):
        return None

    def is_alive(self):
        return False


@pytest.fixture
def tts_setup(monkeypatch, client, fake_supabase, tmp_path):
    """Wire ElevenLabs/OpenAI fakes and seed the content the routes read.

    Depends on ``client`` (not just ``fake_supabase``) so the FastAPI app/`main`
    module — which creates its OWN real ``threading.Thread`` for the rate
    limiter's in-memory storage at import time — is fully imported BEFORE this
    fixture replaces ``threading.Thread`` with the synchronous test double.
    Patching ``threading.Thread`` any earlier breaks that unrelated import.
    """
    monkeypatch.setattr(_threading, "Thread", _SyncThread)

    # SEC-SCOPE-9: seed content already chained to TEACHER_ID's owned discipline
    # (via _LIFECYCLE_CHAPTER) so the owning teacher passes the ownership gate.
    fake_supabase.seed("contents", [
        {"id": "content-1", "body": "Conteudo academico para audio.", "chapter_id": _LIFECYCLE_CHAPTER},
        {"id": "content-2", "body": "Outro conteudo academico.", "chapter_id": _LIFECYCLE_CHAPTER},
    ])
    _seed_owned_course_chapter(fake_supabase)
    fake_supabase.seed("tts_jobs", [])
    fake_supabase.seed("token_usage", [])
    fake_supabase.rpc = fake_supabase._rpc_entry  # type: ignore[attr-defined]
    fake_supabase._rpc_enabled = True

    fake_sync = FakeSyncOpenAI(response_text="Resumo.")
    fake_async = FakeAsyncOpenAI(response_text='{"x": 1}')
    svc = AIService(client=fake_async, sync_client=fake_sync)
    monkeypatch.setattr(routes_ai, "get_ai_service", lambda: svc)
    monkeypatch.setattr(routes_ai, "ELEVENLABS_API_KEY", "fake-key", raising=False)

    import sys

    class _FakeTTS:
        def convert(self, **kwargs):
            yield b"FAKE"
            yield b"MP3"

    class _FakeElevenLabs:
        def __init__(self, api_key=None):
            self.text_to_speech = _FakeTTS()

    el_mod = types.ModuleType("elevenlabs.client")
    el_mod.ElevenLabs = _FakeElevenLabs
    monkeypatch.setitem(sys.modules, "elevenlabs.client", el_mod)

    # The worker recreates a Supabase client off-thread; hand it the SAME fake
    # so job/content mutations are visible to the test via ``fake_supabase``.
    supabase_mod = sys.modules.get("supabase") or types.ModuleType("supabase")
    monkeypatch.setattr(supabase_mod, "create_client", lambda url, key: fake_supabase, raising=False)
    monkeypatch.setitem(sys.modules, "supabase", supabase_mod)

    return svc


# ===========================================================================
# Dedup — same (content_id, audio_type) in flight -> same job_id, 1 dispatch.
# ===========================================================================
class TestDedup:
    def test_two_submits_same_type_return_same_job_id_one_dispatch(
        self, client, as_teacher, fake_supabase, tts_setup, monkeypatch
    ):
        # First submit seeds a `processing` row synchronously (thread patched to
        # run inline) — by the time the response returns, the job has already
        # reached a terminal state in THIS test's synchronous harness. To prove
        # the dedup path itself (not just the terminal state), make the worker
        # a no-op that leaves the row `processing`, so the second submit's
        # dedup check still finds it active.
        monkeypatch.setattr(routes_ai, "_run_tts_job_with_timeout", lambda *a, **k: None)

        first = client.post(
            "/api/ai/audio/generate-from-content",
            json={"content_id": "content-1", "audio_type": "summary"},
        )
        assert first.status_code == 200, first.text
        job_id_1 = first.json()["job_id"]

        second = client.post(
            "/api/ai/audio/generate-from-content",
            json={"content_id": "content-1", "audio_type": "summary"},
        )
        assert second.status_code == 200, second.text
        job_id_2 = second.json()["job_id"]

        assert job_id_1 == job_id_2
        # Only ONE row was ever seeded for this (content_id, audio_type).
        rows = [r for r in fake_supabase.rows("tts_jobs") if r["content_id"] == "content-1"]
        assert len(rows) == 1

    def test_different_audio_type_same_content_not_blocked(
        self, client, as_teacher, fake_supabase, tts_setup, monkeypatch
    ):
        monkeypatch.setattr(routes_ai, "_run_tts_job_with_timeout", lambda *a, **k: None)

        summary_resp = client.post(
            "/api/ai/audio/generate-from-content",
            json={"content_id": "content-1", "audio_type": "summary"},
        )
        podcast_resp = client.post(
            "/api/ai/audio/generate-from-content",
            json={"content_id": "content-1", "audio_type": "podcast"},
        )

        assert summary_resp.status_code == 200
        assert podcast_resp.status_code == 200
        assert summary_resp.json()["job_id"] != podcast_resp.json()["job_id"]

        rows = fake_supabase.rows("tts_jobs")
        types_seeded = {r["audio_type"] for r in rows if r["content_id"] == "content-1"}
        assert types_seeded == {"summary", "podcast"}


# ===========================================================================
# Concurrency cap — a user way over the limit gets 429, no new thread.
# ===========================================================================
class TestConcurrencyCap:
    def test_cap_exceeded_returns_429(self, client, as_teacher, fake_supabase, tts_setup):
        # Seed TTS_MAX_ACTIVE_JOBS_PER_USER already-active jobs for this user.
        for i in range(routes_ai.TTS_MAX_ACTIVE_JOBS_PER_USER):
            fake_supabase.add("tts_jobs", {
                "id": f"active-{i}", "content_id": f"content-{i}", "user_id": TEACHER_ID,
                "audio_type": "summary", "status": "processing",
            })

        resp = client.post(
            "/api/ai/audio/generate-from-content",
            json={"content_id": "content-2", "audio_type": "explanation"},
        )

        assert resp.status_code == 429, resp.text


# ===========================================================================
# Ownership (IDOR) — cross-user poll gets 404, same-owner poll succeeds.
# ===========================================================================
class TestOwnershipOnStatusPoll:
    def test_owner_can_poll_own_job(self, client, as_teacher, fake_supabase, tts_setup):
        fake_supabase.add("tts_jobs", {
            "id": "job-owned", "content_id": "content-1", "user_id": TEACHER_ID,
            "audio_type": "summary", "status": "done", "audio_url": "/uploads/tts/x.mp3",
        })

        resp = client.get("/api/ai/audio/status/job-owned")

        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "done"
        assert resp.json()["audio_url"] == "/uploads/tts/x.mp3"

    def test_cross_user_gets_404_not_the_job(self, client, as_student, fake_supabase, tts_setup):
        # Job belongs to STUDENT_B; STUDENT_A (the ``as_student`` fixture) polls it.
        fake_supabase.add("tts_jobs", {
            "id": "job-other", "content_id": "content-1", "user_id": STUDENT_B_ID,
            "audio_type": "summary", "status": "done", "audio_url": "/uploads/tts/other.mp3",
        })

        resp = client.get("/api/ai/audio/status/job-other")

        assert resp.status_code == 404, resp.text
        # The job row itself is untouched (no pop, no mutation from the failed read).
        assert fake_supabase.find("tts_jobs", id="job-other") is not None

    def test_unknown_job_id_gets_404(self, client, as_teacher, fake_supabase, tts_setup):
        resp = client.get("/api/ai/audio/status/does-not-exist")
        assert resp.status_code == 404


# ===========================================================================
# Non-destructive / idempotent polling via the real route (not just the repo).
# ===========================================================================
class TestIdempotentStatusPoll:
    def test_two_consecutive_polls_after_done_return_same_payload(
        self, client, as_teacher, fake_supabase, tts_setup
    ):
        fake_supabase.add("tts_jobs", {
            "id": "job-poll", "content_id": "content-1", "user_id": TEACHER_ID,
            "audio_type": "summary", "status": "done", "audio_url": "/uploads/tts/y.mp3",
            "duration_estimate": "~1 min",
        })

        first = client.get("/api/ai/audio/status/job-poll")
        second = client.get("/api/ai/audio/status/job-poll")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()
        # The row itself was never popped/deleted.
        assert fake_supabase.find("tts_jobs", id="job-poll") is not None


# ===========================================================================
# End-to-end happy path through the real (synchronous-dispatch) route pair.
# ===========================================================================
class TestEndToEndHappyPath:
    def test_generate_then_poll_reaches_done(self, client, as_teacher, fake_supabase, tts_setup):
        resp = client.post(
            "/api/ai/audio/generate-from-content",
            json={"content_id": "content-1", "audio_type": "summary"},
        )
        assert resp.status_code == 200, resp.text
        job_id = resp.json()["job_id"]

        # Thread ran inline (fixture patches threading.Thread) — the job should
        # already be `done` by the time we poll.
        poll = client.get(f"/api/ai/audio/status/{job_id}")
        assert poll.status_code == 200, poll.text
        assert poll.json()["status"] == "done"
        assert poll.json()["audio_url"].startswith("/uploads/tts/")

        content = fake_supabase.find("contents", id="content-1")
        assert content["audio_url"] == poll.json()["audio_url"]
        assert content["audio_type"] == "summary"


# ===========================================================================
# Timeout — a job that never finishes is forced into `error`, not left
# `processing` forever (POD-4).
# ===========================================================================
class TestTimeout:
    def test_hung_job_is_marked_error_after_timeout(self, monkeypatch, fake_supabase):
        """Drives ``_run_tts_job_with_timeout`` directly (bypassing the route/
        ``client`` fixture, so this test does NOT need the ``threading.Thread``
        patch — it exercises the REAL timeout join with a tiny threshold)."""
        fake_supabase.seed("tts_jobs", [
            {"id": "job-hang", "content_id": "content-1", "user_id": TEACHER_ID,
             "audio_type": "summary", "status": "processing"},
        ])

        import sys as _sys

        supabase_mod = _sys.modules.get("supabase") or types.ModuleType("supabase")
        monkeypatch.setattr(supabase_mod, "create_client", lambda url, key: fake_supabase, raising=False)
        monkeypatch.setitem(_sys.modules, "supabase", supabase_mod)

        # Force the timeout threshold to something the test can wait out.
        monkeypatch.setattr(routes_ai, "TTS_JOB_TIMEOUT_SECONDS", 0.05)

        def _hangs_forever(**kwargs):
            time.sleep(2)  # far longer than the 0.05s timeout above

        monkeypatch.setattr(routes_ai, "_run_tts_job", _hangs_forever)

        routes_ai._run_tts_job_with_timeout(
            job_id="job-hang",
            content_id="content-1",
            content_text="texto",
            audio_type="summary",
            voice_id="21m00Tcm4TlvDq8ikWAM",
            upload_dir="/tmp",
            supabase_url="http://fake",
            supabase_key="fake-key",
            user_id=TEACHER_ID,
        )

        job = TtsJobRepository(fake_supabase).get_by_id("job-hang")
        assert job["status"] == "error", job
        assert "tempo limite" in (job.get("error") or "").lower()


# ===========================================================================
# POD-2 — chunk-and-concatenate: no silent truncation for long narration.
# ===========================================================================
class TestChunkAndConcatenate:
    def test_short_text_is_a_single_chunk(self):
        text = "Uma narracao curta." * 5
        chunks = routes_ai._chunk_text_for_tts(text, max_chars=4500)
        assert chunks == [text]

    def test_long_text_is_split_into_multiple_chunks_preserving_order(self):
        # Build text long enough to force multiple chunks at a small max_chars,
        # with a recognizable marker per paragraph so order is verifiable.
        paragraphs = [f"Paragrafo numero {i}. " * 20 for i in range(10)]
        text = "\n\n".join(paragraphs)

        chunks = routes_ai._chunk_text_for_tts(text, max_chars=200)

        assert len(chunks) > 1
        # No chunk exceeds the cap.
        assert all(len(c) <= 200 for c in chunks)
        # Reassembling preserves the original content in order (modulo the
        # boundary whitespace the splitter trims/collapses).
        rejoined = " ".join(c.strip() for c in chunks)
        for i in range(10):
            assert f"Paragrafo numero {i}." in rejoined
        # Order preserved: paragraph 0 appears before paragraph 9.
        assert rejoined.index("Paragrafo numero 0.") < rejoined.index("Paragrafo numero 9.")

    def test_empty_text_yields_no_chunks_not_a_crash(self):
        # Delegates to the shared ``ai_service.chunk_text`` (POD-1), whose
        # documented contract for empty/whitespace-only input is `[]` ("nothing
        # to narrate") — this route never crashes on it either way, since the
        # HTTP layer already rejects empty ``content_text`` before dispatch.
        assert routes_ai._chunk_text_for_tts("", max_chars=100) == []

    def test_synthesize_mp3_chunks_concatenates_in_order(self):
        class _RecordingTTS:
            def __init__(self):
                self.seen = []

            def convert(self, **kwargs):
                self.seen.append(kwargs["text"])
                # Each chunk's "audio" is a distinguishable byte marker so
                # concatenation order is directly verifiable.
                yield kwargs["text"].encode()

        class _Client:
            def __init__(self):
                self.text_to_speech = _RecordingTTS()

        client = _Client()
        audio = routes_ai._synthesize_mp3_chunks(client, ["a", "b", "c"], "voice-1")

        assert audio == b"abc"
        assert client.text_to_speech.seen == ["a", "b", "c"]

    def test_synthesize_mp3_chunks_aborts_whole_job_on_any_chunk_failure(self):
        """POD-2 AC: a failing chunk must NOT produce a partial/truncated MP3 —
        the whole synthesis aborts (raises) instead of returning partial bytes."""
        class _FailingTTS:
            def __init__(self):
                self.calls = 0

            def convert(self, **kwargs):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("upstream TTS blew up on chunk 2")
                yield kwargs["text"].encode()

        class _Client:
            def __init__(self):
                self.text_to_speech = _FailingTTS()

        client = _Client()

        with pytest.raises(RuntimeError, match="trecho 2/3"):
            routes_ai._synthesize_mp3_chunks(client, ["a", "b", "c"], "voice-1")

    def test_long_narration_end_to_end_produces_one_valid_job(
        self, client, as_teacher, fake_supabase, tts_setup, monkeypatch
    ):
        """A chapter whose narration exceeds one TTS call still reaches a single
        `done` job (chunk-and-concatenate wired end-to-end), never a truncated
        or partial result."""
        long_body = ("Um paragrafo academico bem extenso sobre o tema. " * 300)
        fake_supabase.seed("contents", fake_supabase.rows("contents") + [
            {"id": "content-long", "body": long_body, "chapter_id": _LIFECYCLE_CHAPTER}
        ])
        # Force small chunks so this text genuinely splits into several calls.
        monkeypatch.setattr(routes_ai, "TTS_MAX_CHARS_PER_CALL", 500)

        resp = client.post(
            "/api/ai/audio/generate-from-content",
            json={"content_id": "content-long", "audio_type": "podcast"},
        )
        assert resp.status_code == 200, resp.text
        job_id = resp.json()["job_id"]

        poll = client.get(f"/api/ai/audio/status/{job_id}")
        assert poll.status_code == 200, poll.text
        assert poll.json()["status"] == "done", poll.json()
        assert poll.json()["audio_url"].startswith("/uploads/tts/")
