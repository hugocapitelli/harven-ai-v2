"""GRD-2 — phantom session bug: completed without interaction + invisible to grading.

Two symptoms from the field (student Jeferson, discipline IAA-2026):

  1. A chat session was marked ``completed`` at 0/3 interactions — only the tutor's
     opening message, zero ``role='user'`` turns. Root cause: ``complete_chat_session``
     (``routes_ai.py``) flipped ANY active session to completed with no guard on real
     interaction; the frontend's localStorage ``tutorDone`` flag let "Concluir" fire on
     a fresh 0-turn session. The fix is a server-side guard: no completion without ≥1
     real student message.

  2. The session did not appear in the teacher's grading drill-down. Root cause: the
     grading consumer reads only page 1 of ``GET /disciplines/{id}/sessions`` (default
     ``per_page=20``); a student with >20 sessions loses the older ones. The endpoint
     itself never filters by status/total_messages — proven here — so the fix is on the
     consumer (ask for a high ``per_page``), and this suite pins the endpoint contract.

RED-first: written to fail before the guard exists, pass after. Runs in-process on the
seeded ``FakeSupabaseClient`` (no network / DB), using the shared harness in conftest.py.
"""
from __future__ import annotations

import pytest

from conftest import STUDENT_A_ID, TEACHER_ID, make_seed_tables
from fakes import FakeSupabaseClient

DISC_ID = "disc-grd2"
COURSE_1 = "course-grd2-1"
CHAPTER_1 = "chap-grd2-1"
CONTENT_1 = "content-grd2-1"


def _phantom_seed() -> dict:
    tables = make_seed_tables()
    tables["disciplines"].append({"id": DISC_ID, "name": "Phantom Discipline"})
    tables["discipline_teachers"].append({"discipline_id": DISC_ID, "teacher_id": TEACHER_ID})
    tables["discipline_students"] = [{"discipline_id": DISC_ID, "student_id": STUDENT_A_ID}]
    tables["courses"] = [{"id": COURSE_1, "discipline_id": DISC_ID, "title": "Curso Um"}]
    tables["chapters"] = [{"id": CHAPTER_1, "course_id": COURSE_1, "title": "Cap 1"}]
    tables["contents"] = [{"id": CONTENT_1, "chapter_id": CHAPTER_1, "title": "Conteudo 1"}]
    # A fresh session with ONLY the tutor's opening message (assistant), 0 user turns.
    tables["chat_sessions"] = [
        {"id": "sess-phantom", "user_id": STUDENT_A_ID, "content_id": CONTENT_1,
         "status": "active", "total_messages": 0, "created_at": "2026-01-01T00:00:00Z"},
    ]
    tables["chat_messages"] = [
        {"id": "m-open", "session_id": "sess-phantom", "role": "assistant",
         "content": "Bem-vindo! Vamos refletir...", "created_at": "2026-01-01T00:00:01Z"},
    ]
    tables["session_reviews"] = []
    return tables


@pytest.fixture
def phantom_fake() -> FakeSupabaseClient:
    return FakeSupabaseClient(_phantom_seed())


@pytest.fixture
def phantom_app(phantom_fake, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 48)
    import config
    config.get_settings.cache_clear()
    import database
    import main
    from database import get_supabase
    monkeypatch.setattr(database, "get_supabase", lambda: phantom_fake)
    monkeypatch.setattr(main, "get_supabase", lambda: phantom_fake, raising=False)
    main.app.dependency_overrides[get_supabase] = lambda: phantom_fake
    if hasattr(main.app.state, "limiter"):
        main.app.state.limiter.enabled = False
    yield main.app
    main.app.dependency_overrides.pop(get_supabase, None)


@pytest.fixture
def phantom_client(phantom_app):
    from fastapi.testclient import TestClient
    return TestClient(phantom_app)


def _act_as(app, uid, role):
    from auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: {
        "id": uid, "role": role, "name": uid, "email": f"{uid}@harven.ai",
    }


# ===========================================================================
# Symptom 1 — completion must require real interaction.
# ===========================================================================
class TestNoPhantomCompletion:
    def test_complete_with_zero_user_turns_does_not_complete(self, phantom_fake, phantom_client, phantom_app):
        """A session whose only message is the tutor's opening (0 user turns) must NOT
        be flipped to completed. RED before the guard: the route completes anything."""
        _act_as(phantom_app, STUDENT_A_ID, "STUDENT")
        resp = phantom_client.put("/chat-sessions/sess-phantom/complete")
        assert resp.status_code in (200, 409), resp.text
        # The persisted status must remain 'active' — no phantom completion.
        row = phantom_fake.find("chat_sessions", id="sess-phantom")
        assert row["status"] == "active", (
            f"session was phantom-completed with 0 user turns: status={row['status']}"
        )

    def test_complete_with_real_interaction_still_completes(self, phantom_fake, phantom_client, phantom_app):
        """Regression guard: the legitimate path (>=1 user turn) still completes."""
        phantom_fake.add("chat_messages", {
            "id": "m-user1", "session_id": "sess-phantom", "role": "user",
            "content": "Minha reflexão inicial", "created_at": "2026-01-01T00:00:02Z",
        })
        _act_as(phantom_app, STUDENT_A_ID, "STUDENT")
        resp = phantom_client.put("/chat-sessions/sess-phantom/complete")
        assert resp.status_code == 200, resp.text
        row = phantom_fake.find("chat_sessions", id="sess-phantom")
        assert row["status"] == "completed"


# ===========================================================================
# Symptom 2 — the session must remain visible to grading (no page-1 truncation,
# no status/total_messages filter dropping it).
# ===========================================================================
class TestSessionVisibleToGrading:
    def test_completed_low_message_session_is_listed(self, phantom_fake, phantom_client, phantom_app):
        """A completed session with few messages must appear in the grading list —
        the endpoint must not filter by status or total_messages."""
        # Mark the phantom completed directly in the store to simulate legacy data.
        for r in phantom_fake._tables["chat_sessions"]:
            if r["id"] == "sess-phantom":
                r["status"] = "completed"
        _act_as(phantom_app, TEACHER_ID, "TEACHER")
        resp = phantom_client.get(f"/disciplines/{DISC_ID}/sessions", params={"student_id": STUDENT_A_ID})
        assert resp.status_code == 200, resp.text
        ids = {row["id"] for row in resp.json()["data"]}
        assert "sess-phantom" in ids, "completed low-message session missing from grading list"

    def test_older_session_beyond_page_one_still_returned(self, phantom_fake, phantom_client, phantom_app):
        """A student with >20 sessions must still expose ALL of them to grading — the
        target session cannot be hidden behind default per_page=20 pagination.

        RED before the fix: a caller that only reads page 1 (default per_page) loses
        the 21st+ sessions. This test asserts the endpoint CAN return them when asked
        for a large page — proving the fix (consumer requests a high per_page) is
        sufficient and the data is not otherwise dropped."""
        # Seed 25 extra active sessions for the same student/content so the phantom
        # (oldest, created first) sits well beyond the default page-1 window when
        # ordered by created_at DESC.
        for i in range(25):
            phantom_fake.add("chat_sessions", {
                "id": f"sess-extra-{i}", "user_id": STUDENT_A_ID, "content_id": CONTENT_1,
                "status": "completed", "total_messages": 4,
                "created_at": f"2026-02-{(i % 27) + 1:02d}T00:00:00Z",
            })
        _act_as(phantom_app, TEACHER_ID, "TEACHER")

        # Default page (per_page=20) would NOT contain the oldest phantom session.
        default_ids = {r["id"] for r in phantom_client.get(
            f"/disciplines/{DISC_ID}/sessions", params={"student_id": STUDENT_A_ID}
        ).json()["data"]}
        assert "sess-phantom" not in default_ids, (
            "precondition: phantom should be off page 1 with 26 sessions"
        )

        # Asking for a large page surfaces every session, including the phantom.
        big_ids = {r["id"] for r in phantom_client.get(
            f"/disciplines/{DISC_ID}/sessions",
            params={"student_id": STUDENT_A_ID, "per_page": 100},
        ).json()["data"]}
        assert "sess-phantom" in big_ids, "grading must be able to see ALL student sessions"
        assert len(big_ids) == 26
