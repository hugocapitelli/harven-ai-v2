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

    def test_restart_with_multiple_completed_rows_does_not_break(self, client, as_student, fake_supabase):
        """Iteration-2 root cause: after a restart (or GRD-2 phantom) the pair
        ``(user_id, content_id)`` has >=2 rows. ``create_or_get_chat_session`` used a
        BARE ``.maybe_single()`` which raises on >1 row in real Supabase (PGRST116) →
        endpoint 500 or resolves a stale/ambiguous COMPLETED row, so the kickoff runs
        against a finished session (finalized 0/3) and the panel snaps back — the dead
        "refazer → trava → refazer" loop. The fix orders by newest + limit(1) (mirrors
        ``get_session_by_content``). This proves the endpoint resolves cleanly and
        creates a NEW distinct active attempt even with several completed rows."""
        # Two completed sessions already exist for the pair (real post-restart state).
        fake_supabase.add("chat_sessions", {
            "id": "done-1", "user_id": STUDENT_A_ID, "content_id": "content-multi",
            "status": "completed", "total_messages": 6, "initial_question_text": "PERGUNTA FIXA",
            "created_at": "2026-01-01T00:00:00Z",
        })
        fake_supabase.add("chat_sessions", {
            "id": "done-2", "user_id": STUDENT_A_ID, "content_id": "content-multi",
            "status": "completed", "total_messages": 4, "initial_question_text": "PERGUNTA FIXA",
            "created_at": "2026-01-02T00:00:00Z",
        })

        resp = client.post(
            "/chat-sessions",
            json={"content_id": "content-multi", "initial_question_text": "PERGUNTA FIXA"},
        )
        assert resp.status_code in (200, 201), resp.text
        body = resp.json()
        # A brand-new distinct ACTIVE session — not either completed row.
        assert body["id"] not in ("done-1", "done-2")
        assert body["status"] == "active"
        assert body["initial_question_text"] == "PERGUNTA FIXA"

        rows = [
            r for r in fake_supabase.rows("chat_sessions")
            if r["content_id"] == "content-multi" and r["user_id"] == STUDENT_A_ID
        ]
        # Both completed rows survive (history preserved) + the new active one.
        assert len(rows) == 3
        assert sum(1 for r in rows if r["status"] == "completed") == 2
        assert sum(1 for r in rows if r["status"] == "active") == 1

    def test_restart_when_newest_is_active_resumes_not_duplicates(self, client, as_student, fake_supabase):
        """Guard the other direction: if the NEWEST session is already ``active`` (e.g.
        a restart just created it and the effect re-fires), create-or-get must RESUME it
        (same id, no new row), never stack a second active attempt."""
        fake_supabase.add("chat_sessions", {
            "id": "old-done", "user_id": STUDENT_A_ID, "content_id": "content-resume",
            "status": "completed", "total_messages": 6, "initial_question_text": "Q",
            "created_at": "2026-01-01T00:00:00Z",
        })
        fake_supabase.add("chat_sessions", {
            "id": "fresh-active", "user_id": STUDENT_A_ID, "content_id": "content-resume",
            "status": "active", "total_messages": 0, "initial_question_text": "Q",
            "created_at": "2026-02-01T00:00:00Z",
        })
        resp = client.post(
            "/chat-sessions",
            json={"content_id": "content-resume", "initial_question_text": "Q"},
        )
        assert resp.status_code in (200, 201), resp.text
        # Newest is active → resumed, same id, no new row.
        assert resp.json()["id"] == "fresh-active"
        rows = [
            r for r in fake_supabase.rows("chat_sessions")
            if r["content_id"] == "content-resume" and r["user_id"] == STUDENT_A_ID
        ]
        assert len(rows) == 2  # unchanged — no duplicate active session

    def test_race_fallback_reread_with_multiple_rows_does_not_break(self, fake_supabase, monkeypatch):
        """GRD-3 it3 (issue it2-1): the race-condition fallback in
        ``_upsert_chat_session_row`` re-reads the surviving row after a losing insert.
        That re-read must ALSO resolve the newest via ``.order().limit(1)`` — a bare
        ``.maybe_single()`` there raises PGRST116 when ``(user_id, content_id)`` already
        has >1 row (the exact twin of the it2 bug, on the race path).

        Force the ``except`` branch deterministically: seed two completed rows for the
        pair, then make the insert raise (a concurrent insert won the unique race). With
        the fix the fallback re-read resolves the NEWEST row cleanly and returns it; with
        the old bare ``.maybe_single()`` the faithful fake raises PGRST116 (red)."""
        import routes_ai

        uid, cid = STUDENT_A_ID, "content-race"
        fake_supabase.add("chat_sessions", {
            "id": "race-done-1", "user_id": uid, "content_id": cid,
            "status": "completed", "total_messages": 6, "initial_question_text": "Q",
            "created_at": "2026-01-01T00:00:00Z",
        })
        fake_supabase.add("chat_sessions", {
            "id": "race-done-2", "user_id": uid, "content_id": cid,
            "status": "completed", "total_messages": 4, "initial_question_text": "Q",
            "created_at": "2026-01-02T00:00:00Z",
        })

        # Simulate the lost race: the fallback insert raises (concurrent insert won the
        # unique index), driving _upsert_chat_session_row into its re-read ``except``.
        def _boom(*_a, **_k):
            raise Exception("duplicate key value violates unique constraint")

        monkeypatch.setattr(routes_ai, "_create_chat_session_row", _boom)

        # Direct call into the branch under test (default fake has no rpc → fallback).
        row = routes_ai._upsert_chat_session_row(fake_supabase, uid, cid, "Q")
        # The re-read resolved the NEWEST surviving row without raising PGRST116.
        assert row["id"] == "race-done-2"

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
