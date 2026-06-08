"""Pytest bootstrap for the Harven backend security suite.

The backend uses bare imports (`from config import ...`, `from auth import ...`),
so the `backend/` directory must be importable. We insert it onto sys.path here
and provide shared fixtures for env isolation.

Ownership / history
-------------------
* The Phase-1 portion (sys.path bootstrap + `STRONG_SECRET` + `_clear_settings_cache`)
  was created by SEC-ATO and powers `test_security_hotfix.py`. **Do not clobber it.**
* SEC-ADMIN-1 extends this file (it does not recreate it) with the IDOR harness:
  the shared `FakeSupabaseClient` (defined in `fakes.py`), the FastAPI `app`/`client`
  fixtures, the `as_student`/`as_teacher`/`as_admin` actor overrides, and the
  deterministic `seed`. SEC-AUTHZ-0 contributes `authz`-level unit coverage that
  imports the same fake. These fixtures are the stable contract for SEC-ADMIN-2..5.
"""
import os
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# Also expose the tests/ dir so sibling helper modules (`fakes`, `idor_helpers`)
# import as top-level modules regardless of pytest's rootdir/import-mode.
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)


# A strong, arbitrary secret used wherever a valid signing key is required.
STRONG_SECRET = "x" * 48  # 48 chars, not in the weak blacklist


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Ensure each test sees a freshly validated Settings instance.

    `config.get_settings` is `@lru_cache`d, so without clearing it the first
    test's environment would leak into the others.
    """
    try:
        import config

        config.get_settings.cache_clear()
    except Exception:
        pass
    yield
    try:
        import config

        config.get_settings.cache_clear()
    except Exception:
        pass


# ===========================================================================
# SEC-ADMIN-1 — IDOR test harness (in-process, no network / no DB)
# ===========================================================================
# The fake Supabase client lives in `fakes.py` so it can be imported by any test
# module (`from fakes import FakeSupabaseClient`) as well as exposed via fixtures.
from fakes import FakeSupabaseClient  # noqa: E402  (after sys.path bootstrap)

# ---------------------------------------------------------------------------
# Deterministic seed identities — stable IDs reused by SEC-ADMIN-2..5.
# 2 students + 1 teacher + 1 admin, plus related rows keyed by these IDs.
# ---------------------------------------------------------------------------
STUDENT_A_ID = "student-a"
STUDENT_B_ID = "student-b"
TEACHER_ID = "teacher-1"
ADMIN_ID = "admin-1"

DISCIPLINE_ID = "discipline-1"          # owned by TEACHER_ID
OTHER_DISCIPLINE_ID = "discipline-2"    # NOT owned by TEACHER_ID

SESSION_A_ID = "session-a"              # owned by STUDENT_A_ID
SESSION_B_ID = "session-b"              # owned by STUDENT_B_ID
NOTIFICATION_A_ID = "notif-a"           # belongs to STUDENT_A_ID
NOTIFICATION_B_ID = "notif-b"           # belongs to STUDENT_B_ID
REVIEW_A_ID = "review-a"                # authored by STUDENT_A_ID
PROGRESS_A_ID = "progress-a"            # course progress of STUDENT_A_ID
SETTINGS_ID = "settings-1"             # singleton system_settings row (SEC-ROT-*)


def _user(uid: str, role: str, name: str) -> dict:
    return {
        "id": uid,
        "role": role,
        "name": name,
        "email": f"{uid}@harven.ai",
    }


def make_seed_tables() -> dict:
    """Build the deterministic seed as plain dicts (one fresh copy per call)."""
    return {
        "users": [
            _user(STUDENT_A_ID, "STUDENT", "Student A"),
            _user(STUDENT_B_ID, "STUDENT", "Student B"),
            _user(TEACHER_ID, "TEACHER", "Teacher One"),
            _user(ADMIN_ID, "ADMIN", "Admin One"),
        ],
        "chat_sessions": [
            {"id": SESSION_A_ID, "user_id": STUDENT_A_ID, "content_id": "content-1",
             "status": "active", "total_messages": 1},
            {"id": SESSION_B_ID, "user_id": STUDENT_B_ID, "content_id": "content-2",
             "status": "active", "total_messages": 1},
        ],
        "chat_messages": [
            {"id": "msg-a1", "session_id": SESSION_A_ID, "role": "user",
             "content": "hello from A", "created_at": "2026-01-01T00:00:00Z"},
            {"id": "msg-b1", "session_id": SESSION_B_ID, "role": "user",
             "content": "hello from B", "created_at": "2026-01-01T00:00:00Z"},
        ],
        "notifications": [
            {"id": NOTIFICATION_A_ID, "user_id": STUDENT_A_ID, "title": "A",
             "read": False},
            {"id": NOTIFICATION_B_ID, "user_id": STUDENT_B_ID, "title": "B",
             "read": False},
        ],
        "reviews": [
            {"id": REVIEW_A_ID, "user_id": STUDENT_A_ID, "session_id": SESSION_A_ID,
             "body": "review by A"},
        ],
        "course_progress": [
            {"id": PROGRESS_A_ID, "user_id": STUDENT_A_ID, "course_id": "course-1",
             "points": 10, "certificate": False},
        ],
        "disciplines": [
            {"id": DISCIPLINE_ID, "title": "Owned Discipline"},
            {"id": OTHER_DISCIPLINE_ID, "title": "Other Discipline"},
        ],
        "discipline_teachers": [
            {"discipline_id": DISCIPLINE_ID, "teacher_id": TEACHER_ID},
        ],
        "discipline_students": [
            {"discipline_id": DISCIPLINE_ID, "student_id": STUDENT_A_ID},
        ],
        # SEC-ROT-*: singleton settings row. jwt_secret starts NULL so the
        # provider's seed-on-NULL path is exercised; force_logout rotates it.
        "system_settings": [
            {"id": SETTINGS_ID, "platform_name": "Harven.AI",
             "jwt_secret": None, "jwt_secret_rotated_at": None},
        ],
        # force_logout / admin _log append here; seed empty so writes are visible.
        "system_logs": [],
    }


@pytest.fixture
def fake_supabase() -> FakeSupabaseClient:
    """A fresh, deterministically-seeded fake Supabase client per test."""
    return FakeSupabaseClient(make_seed_tables())


# Backwards/role-clarity alias — the seeded fake IS the seed.
@pytest.fixture
def seed(fake_supabase: FakeSupabaseClient) -> FakeSupabaseClient:
    """Alias for `fake_supabase`; named `seed` to match the story's fixture name."""
    return fake_supabase


@pytest.fixture
def app(fake_supabase: FakeSupabaseClient, monkeypatch):
    """The FastAPI app with the Supabase dependency overridden by the fake.

    A strong JWT secret + non-production env let `main` import past the Phase-1
    boot guard without a real key. `database.get_supabase` is patched at module
    level so both `Depends(get_supabase)` *and* the direct call in `/health`
    resolve to the fake. No network, no DB.
    """
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", STRONG_SECRET)

    import config
    config.get_settings.cache_clear()

    import database
    import main
    from database import get_supabase

    # Direct module-level calls (e.g. /health) bypass Depends — patch the source.
    monkeypatch.setattr(database, "get_supabase", lambda: fake_supabase)
    monkeypatch.setattr(main, "get_supabase", lambda: fake_supabase, raising=False)
    # Dependency-injected call sites.
    main.app.dependency_overrides[get_supabase] = lambda: fake_supabase

    # The rate limiter would block tight test loops.
    if hasattr(main.app.state, "limiter"):
        main.app.state.limiter.enabled = False

    yield main.app

    main.app.dependency_overrides.pop(get_supabase, None)


@pytest.fixture
def client(app):
    """A `TestClient` bound to the fake-backed app."""
    from fastapi.testclient import TestClient
    return TestClient(app)


def _override_current_user(app, user: dict):
    """Override `auth.get_current_user` to act as `user` (no real JWT)."""
    from auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: dict(user)


@pytest.fixture
def as_student(app):
    """Act as STUDENT_A (the canonical "owner" actor in IDOR tests)."""
    user = _user(STUDENT_A_ID, "STUDENT", "Student A")
    _override_current_user(app, user)
    return user


@pytest.fixture
def as_other_student(app):
    """Act as STUDENT_B (the canonical "cross actor" in IDOR tests)."""
    user = _user(STUDENT_B_ID, "STUDENT", "Student B")
    _override_current_user(app, user)
    return user


@pytest.fixture
def as_teacher(app):
    user = _user(TEACHER_ID, "TEACHER", "Teacher One")
    _override_current_user(app, user)
    return user


@pytest.fixture
def as_admin(app):
    user = _user(ADMIN_ID, "ADMIN", "Admin One")
    _override_current_user(app, user)
    return user


# ===========================================================================
# ASYNC-AI-3 — async LLM harness fixtures (live-fake + MOCK_MODE)
# ===========================================================================
# These power test_concurrency / test_ai_service_methods / test_tts_job. They keep
# the whole async suite headless: no OPENAI_API_KEY, no ElevenLabs, no network.
from fakes import FakeAsyncOpenAI, FakeSyncOpenAI  # noqa: E402


def make_ai_service(
    *,
    delay: float = 0.0,
    response_text: str = '{"questions": []}',
    transcribe_text: str = "transcribed text",
    sync_delay: float = 0.0,
    sync_response_text: str = "summarized content",
):
    """Build an ``AIService`` with injected fake clients (live-fake, mock_mode=False).

    Uses the ASYNC-AI-1 injection points (``client`` / ``sync_client``) so the real
    OpenAI constructors are never touched. ``mock_mode`` is forced off, so the public
    methods exercise the real ``_call_openai`` path against the fake.
    """
    from services.ai_service import AIService

    fake_async = FakeAsyncOpenAI(
        delay=delay, response_text=response_text, transcribe_text=transcribe_text
    )
    fake_sync = FakeSyncOpenAI(delay=sync_delay, response_text=sync_response_text)
    svc = AIService(client=fake_async, sync_client=fake_sync)
    return svc, fake_async, fake_sync


@pytest.fixture
def ai_service_factory():
    """Factory fixture returning :func:`make_ai_service` (per-test configuration)."""
    return make_ai_service


@pytest.fixture
def mock_ai_service(monkeypatch):
    """An ``AIService`` forced into MOCK_MODE (no API key) — canned-fallback path.

    Ensures the OPENAI key is absent so ``__init__`` selects ``mock_mode=True`` and no
    real client is constructed; the public methods must still return valid shapes via
    their ``_mock_*`` / canned fallbacks without touching the network.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "")

    import config
    config.get_settings.cache_clear()

    from services.ai_service import AIService

    svc = AIService()
    assert svc.mock_mode is True
    assert svc.client is None
    return svc
