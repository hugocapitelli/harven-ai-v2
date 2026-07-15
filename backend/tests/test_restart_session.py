"""GRD-3 — "Refazer sessão": restarting a completed (incl. phantom) session.

The student was trapped: a session marked ``completed`` — including the phantom
completed-with-0-turns case (GRD-2) — showed "Sessão concluída" with no path back
to the tutor. The fix adds a frontend "Refazer sessão" that starts a fresh attempt
via the EXISTING create-or-get endpoint. This suite pins the backend guarantee that
"Refazer" depends on:

  * restarting a completed session (even a phantom, 0 messages, and even reusing the
    SAME question the student is locked into per SOC-1) creates a NEW distinct
    ``active`` session — never reactivates the completed one (SEC-CHAT-3);
  * the completed session SURVIVES in the store, so the teacher's grading drill-down
    (GRD-1) keeps the full history — nothing is deleted.

SOC-1 already covers completed → new attempt with a DIFFERENT question; the Hugo case
is the SAME fixed question on a phantom row, which this file adds. Runs in-process on
the shared ``FakeSupabaseClient`` (no network / DB) via conftest's harness.
"""
from __future__ import annotations

from conftest import STUDENT_A_ID


class TestRestartPhantomSession:
    def test_restart_phantom_completed_zero_turns_spawns_new_session(self, client, as_student, fake_supabase):
        """A phantom session (completed, 0 messages) must not trap the student: a new
        create for the same content spawns a fresh active session, phantom preserved."""
        fake_supabase.add("chat_sessions", {
            "id": "phantom-sess", "user_id": STUDENT_A_ID, "content_id": "content-grd3",
            "status": "completed", "total_messages": 0,
            "initial_question_text": "PERGUNTA FIXA",
        })

        resp = client.post(
            "/chat-sessions",
            json={"content_id": "content-grd3", "initial_question_text": "PERGUNTA FIXA"},
        )
        assert resp.status_code in (200, 201), resp.text
        body = resp.json()
        # Distinct NEW session, active, not the phantom.
        assert body["id"] != "phantom-sess"
        assert body["status"] == "active"
        # SOC-1: the same fixed question carries onto the fresh attempt.
        assert body["initial_question_text"] == "PERGUNTA FIXA"

        rows = [
            r for r in fake_supabase.rows("chat_sessions")
            if r["content_id"] == "content-grd3" and r["user_id"] == STUDENT_A_ID
        ]
        # History preserved: the phantom completed row survives alongside the new one.
        assert len(rows) == 2
        statuses = sorted(r["status"] for r in rows)
        assert statuses == ["active", "completed"]
        assert any(r["id"] == "phantom-sess" and r["status"] == "completed" for r in rows)

    def test_by_content_returns_the_new_active_after_restart(self, client, as_student, fake_supabase):
        """After restart, ``by-content`` (most-recent) resolves to the fresh active
        session, so the panel re-hydrates unlocked and ready to interact."""
        fake_supabase.add("chat_sessions", {
            "id": "phantom-sess-2", "user_id": STUDENT_A_ID, "content_id": "content-grd3b",
            "status": "completed", "total_messages": 0,
            "initial_question_text": "Q",
            "created_at": "2026-01-01T00:00:00Z",
        })
        created = client.post(
            "/chat-sessions",
            json={"content_id": "content-grd3b", "initial_question_text": "Q"},
        )
        assert created.status_code in (200, 201), created.text
        new_id = created.json()["id"]

        # Give the new row a strictly-later created_at so "most recent" is deterministic
        # against the seeded phantom.
        for r in fake_supabase._tables["chat_sessions"]:
            if r["id"] == new_id:
                r["created_at"] = "2026-02-01T00:00:00Z"

        resp = client.get("/chat-sessions/by-content/content-grd3b")
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == new_id
        assert resp.json()["status"] == "active"
