"""TTSJOB-1 — TtsJobRepository regression suite (Phase 4, EPIC-PODCAST).

Fail-before / pass-after oracle for the durable TTS/podcast job data layer that
replaces the volatile in-memory ``_tts_jobs`` dict in ``routes_ai.py`` (bug
sweep #34, #58, #59). Every test runs headless against the in-process
``FakeSupabaseClient`` (no network/DB).

Contract under test:
  * ``get_for_content(content_id, user_id)`` — IDOR guard. Returns the job only
    when BOTH ``content_id`` AND ``user_id`` match; a cross-actor ``user_id``
    (or content owned by someone else) returns ``None``, never a leaked row.
  * ``sweep_expired`` — TTL sweep restricted to terminal states (``done``/
    ``error``); a ``processing`` row, however old, is NEVER selected/deleted.
  * ``seed_processing`` — idempotent creation: seeding the same ``job_id``
    twice never creates a duplicate row nor corrupts existing state.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import STUDENT_A_ID, STUDENT_B_ID
from fakes import FakeSupabaseClient
from repositories.tts_job_repo import TtsJobRepository

CONTENT_A_ID = "content-a"
CONTENT_B_ID = "content-b"


def _fake(rows=None) -> FakeSupabaseClient:
    return FakeSupabaseClient({"tts_jobs": rows or []})


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


class TestSeedProcessing:
    def test_seed_creates_processing_row(self):
        fake = _fake()
        repo = TtsJobRepository(fake)
        job = repo.seed_processing("job-1", CONTENT_A_ID, STUDENT_A_ID, "podcast")
        assert job["status"] == "processing"
        assert job["user_id"] == STUDENT_A_ID
        assert job["content_id"] == CONTENT_A_ID
        assert job["audio_type"] == "podcast"
        assert fake.find("tts_jobs", id="job-1") is not None

    def test_seed_is_idempotent_no_duplicate(self):
        fake = _fake()
        repo = TtsJobRepository(fake)
        first = repo.seed_processing("job-1", CONTENT_A_ID, STUDENT_A_ID, "summary")
        second = repo.seed_processing("job-1", CONTENT_A_ID, STUDENT_A_ID, "summary")
        # Same row returned, no duplicate created.
        assert first["id"] == second["id"]
        assert len(fake.rows("tts_jobs")) == 1

    def test_seed_twice_does_not_corrupt_existing_state(self):
        # Job already transitioned to done; a second "seed" call must not
        # revert it back to processing (idempotency must not clobber state).
        fake = _fake([
            {"id": "job-1", "content_id": CONTENT_A_ID, "user_id": STUDENT_A_ID,
             "audio_type": "summary", "status": "done", "audio_url": "/uploads/tts/x.mp3"},
        ])
        repo = TtsJobRepository(fake)
        result = repo.seed_processing("job-1", CONTENT_A_ID, STUDENT_A_ID, "summary")
        assert result["status"] == "done"
        assert result["audio_url"] == "/uploads/tts/x.mp3"


class TestLifecycleTransitions:
    def test_mark_done_sets_status_and_audio_url(self):
        fake = _fake()
        repo = TtsJobRepository(fake)
        repo.seed_processing("job-1", CONTENT_A_ID, STUDENT_A_ID)
        updated = repo.mark_done("job-1", "/uploads/tts/out.mp3", "~2 min")
        assert updated["status"] == "done"
        assert updated["audio_url"] == "/uploads/tts/out.mp3"
        assert updated["duration_estimate"] == "~2 min"

    def test_mark_error_sets_status_and_error(self):
        fake = _fake()
        repo = TtsJobRepository(fake)
        repo.seed_processing("job-1", CONTENT_A_ID, STUDENT_A_ID)
        updated = repo.mark_error("job-1", "ElevenLabs timeout")
        assert updated["status"] == "error"
        assert updated["error"] == "ElevenLabs timeout"


class TestGetForContentIdorGuard:
    def test_owner_gets_the_job(self):
        fake = _fake([
            {"id": "job-1", "content_id": CONTENT_A_ID, "user_id": STUDENT_A_ID,
             "audio_type": "podcast", "status": "done", "audio_url": "/x.mp3",
             "created_at": "2026-07-01T00:00:00Z"},
        ])
        repo = TtsJobRepository(fake)
        result = repo.get_for_content(CONTENT_A_ID, STUDENT_A_ID)
        assert result is not None
        assert result["id"] == "job-1"

    def test_cross_actor_gets_nothing(self):
        # Job belongs to STUDENT_A; STUDENT_B queries the SAME content_id.
        fake = _fake([
            {"id": "job-1", "content_id": CONTENT_A_ID, "user_id": STUDENT_A_ID,
             "audio_type": "podcast", "status": "done", "audio_url": "/x.mp3",
             "created_at": "2026-07-01T00:00:00Z"},
        ])
        repo = TtsJobRepository(fake)
        result = repo.get_for_content(CONTENT_A_ID, STUDENT_B_ID)
        # No row leaked to the wrong actor — never falls back to content_id-only.
        assert result is None

    def test_never_filters_by_content_id_alone(self):
        # Two different owners, same content_id (edge case / re-generation).
        fake = _fake([
            {"id": "job-1", "content_id": CONTENT_A_ID, "user_id": STUDENT_A_ID,
             "audio_type": "summary", "status": "done", "audio_url": "/a.mp3",
             "created_at": "2026-07-01T00:00:00Z"},
            {"id": "job-2", "content_id": CONTENT_A_ID, "user_id": STUDENT_B_ID,
             "audio_type": "summary", "status": "done", "audio_url": "/b.mp3",
             "created_at": "2026-07-02T00:00:00Z"},
        ])
        repo = TtsJobRepository(fake)
        as_a = repo.get_for_content(CONTENT_A_ID, STUDENT_A_ID)
        as_b = repo.get_for_content(CONTENT_A_ID, STUDENT_B_ID)
        assert as_a["id"] == "job-1"
        assert as_b["id"] == "job-2"

    def test_wrong_content_id_returns_none(self):
        fake = _fake([
            {"id": "job-1", "content_id": CONTENT_A_ID, "user_id": STUDENT_A_ID,
             "audio_type": "summary", "status": "done", "audio_url": "/a.mp3",
             "created_at": "2026-07-01T00:00:00Z"},
        ])
        repo = TtsJobRepository(fake)
        result = repo.get_for_content(CONTENT_B_ID, STUDENT_A_ID)
        assert result is None


class TestActiveJobHelpers:
    def test_get_active_for_content_finds_processing_job(self):
        fake = _fake([
            {"id": "job-1", "content_id": CONTENT_A_ID, "user_id": STUDENT_A_ID,
             "audio_type": "podcast", "status": "processing"},
        ])
        repo = TtsJobRepository(fake)
        result = repo.get_active_for_content(CONTENT_A_ID, "podcast", STUDENT_A_ID)
        assert result is not None
        assert result["id"] == "job-1"

    def test_get_active_for_content_ignores_terminal_jobs(self):
        fake = _fake([
            {"id": "job-1", "content_id": CONTENT_A_ID, "user_id": STUDENT_A_ID,
             "audio_type": "podcast", "status": "done"},
        ])
        repo = TtsJobRepository(fake)
        result = repo.get_active_for_content(CONTENT_A_ID, "podcast", STUDENT_A_ID)
        assert result is None

    def test_get_active_for_content_ignores_other_users(self):
        fake = _fake([
            {"id": "job-1", "content_id": CONTENT_A_ID, "user_id": STUDENT_A_ID,
             "audio_type": "podcast", "status": "processing"},
        ])
        repo = TtsJobRepository(fake)
        result = repo.get_active_for_content(CONTENT_A_ID, "podcast", STUDENT_B_ID)
        assert result is None

    def test_count_active_for_user(self):
        fake = _fake([
            {"id": "job-1", "user_id": STUDENT_A_ID, "status": "processing"},
            {"id": "job-2", "user_id": STUDENT_A_ID, "status": "processing"},
            {"id": "job-3", "user_id": STUDENT_A_ID, "status": "done"},
            {"id": "job-4", "user_id": STUDENT_B_ID, "status": "processing"},
        ])
        repo = TtsJobRepository(fake)
        assert repo.count_active_for_user(STUDENT_A_ID) == 2
        assert repo.count_active_for_user(STUDENT_B_ID) == 1


class TestSweepExpired:
    def test_sweep_preserves_processing_regardless_of_age(self):
        very_old = _iso(datetime.now(timezone.utc) - timedelta(days=30))
        fake = _fake([
            {"id": "job-old-processing", "user_id": STUDENT_A_ID, "status": "processing",
             "created_at": very_old, "updated_at": very_old},
        ])
        repo = TtsJobRepository(fake)
        deleted = repo.sweep_expired(ttl=timedelta(hours=1))
        assert deleted == []
        assert fake.find("tts_jobs", id="job-old-processing") is not None

    def test_sweep_removes_expired_terminal_jobs(self):
        very_old = _iso(datetime.now(timezone.utc) - timedelta(days=30))
        fake = _fake([
            {"id": "job-old-done", "user_id": STUDENT_A_ID, "status": "done",
             "created_at": very_old, "updated_at": very_old},
            {"id": "job-old-error", "user_id": STUDENT_A_ID, "status": "error",
             "created_at": very_old, "updated_at": very_old},
        ])
        repo = TtsJobRepository(fake)
        deleted = repo.sweep_expired(ttl=timedelta(hours=1))
        deleted_ids = {row["id"] for row in deleted}
        assert deleted_ids == {"job-old-done", "job-old-error"}
        assert fake.find("tts_jobs", id="job-old-done") is None
        assert fake.find("tts_jobs", id="job-old-error") is None

    def test_sweep_keeps_recent_terminal_jobs(self):
        recent = _iso(datetime.now(timezone.utc) - timedelta(minutes=5))
        fake = _fake([
            {"id": "job-recent-done", "user_id": STUDENT_A_ID, "status": "done",
             "created_at": recent, "updated_at": recent},
        ])
        repo = TtsJobRepository(fake)
        deleted = repo.sweep_expired(ttl=timedelta(hours=1))
        assert deleted == []
        assert fake.find("tts_jobs", id="job-recent-done") is not None

    def test_sweep_mixed_batch_only_removes_expired_terminal(self):
        very_old = _iso(datetime.now(timezone.utc) - timedelta(days=30))
        recent = _iso(datetime.now(timezone.utc) - timedelta(minutes=1))
        fake = _fake([
            {"id": "job-1", "user_id": STUDENT_A_ID, "status": "processing",
             "created_at": very_old, "updated_at": very_old},  # old but in-flight -> KEEP
            {"id": "job-2", "user_id": STUDENT_A_ID, "status": "done",
             "created_at": very_old, "updated_at": very_old},  # old + terminal -> REMOVE
            {"id": "job-3", "user_id": STUDENT_A_ID, "status": "error",
             "created_at": recent, "updated_at": recent},      # recent + terminal -> KEEP
        ])
        repo = TtsJobRepository(fake)
        deleted = repo.sweep_expired(ttl=timedelta(hours=1))
        deleted_ids = {row["id"] for row in deleted}
        assert deleted_ids == {"job-2"}
        remaining_ids = {row["id"] for row in fake.rows("tts_jobs")}
        assert remaining_ids == {"job-1", "job-3"}
