"""SOC-1 — durable socratic-question lock per (user, content).

Backend contract for ``chat_sessions.initial_question_text`` (goal:
docs/goals/GOAL-pergunta-unica.md). Each test is a fail-before / pass-after
oracle against the in-memory FakeSupabaseClient (no network / no DB), matching
the TPP-2 harness style in ``test_tutor_persistence.py``:

  (a) creation persists the chosen question and echoes it back;
  (b) a second create-or-get with a DIFFERENT question returns the SAME session
      with the ORIGINAL question intact (first-write-wins);
  (c) ``GET /chat-sessions/by-content/{content_id}`` surfaces the stored question;
  (d) after the session is ``completed``, a new create with another question
      spawns a NEW session carrying the NEW question (SEC-CHAT-3 preserved).

Both the race-free RPC path and the no-RPC fallback insert are exercised so the
write-once behavior holds regardless of whether migration B is applied.
"""
from __future__ import annotations

import pytest

from conftest import STUDENT_A_ID


def _enable_rpc(fake_supabase, monkeypatch):
    """Flip the fake into the migration-B (upsert RPC) path, like TPP-2 does."""
    monkeypatch.setattr(fake_supabase, "rpc", fake_supabase._rpc_entry, raising=False)
    fake_supabase._rpc_enabled = True


# ---------------------------------------------------------------------------
# (a) creation persists the chosen question and echoes it back
# ---------------------------------------------------------------------------
class TestCreationPersistsQuestion:
    def test_create_with_rpc_persists_and_echoes(self, client, as_student, fake_supabase, monkeypatch):
        _enable_rpc(fake_supabase, monkeypatch)
        q = "O que torna um argumento valido?"
        resp = client.post(
            "/chat-sessions",
            json={"content_id": "content-soc1-a", "initial_question_text": q},
        )
        assert resp.status_code in (200, 201), resp.text
        assert resp.json()["initial_question_text"] == q
        stored = fake_supabase.find(
            "chat_sessions", user_id=STUDENT_A_ID, content_id="content-soc1-a"
        )
        assert stored["initial_question_text"] == q

    def test_create_via_fallback_persists_and_echoes(self, client, as_student, fake_supabase):
        # Default fake has no rpc → route fallback insert must still persist it.
        q = "Por que a premissa e necessaria?"
        resp = client.post(
            "/chat-sessions",
            json={"content_id": "content-soc1-fb", "initial_question_text": q},
        )
        assert resp.status_code in (200, 201), resp.text
        assert resp.json()["initial_question_text"] == q
        stored = fake_supabase.find(
            "chat_sessions", user_id=STUDENT_A_ID, content_id="content-soc1-fb"
        )
        assert stored["initial_question_text"] == q


# ---------------------------------------------------------------------------
# (b) create-or-get with a DIFFERENT question → same session, ORIGINAL question
# ---------------------------------------------------------------------------
class TestResumeNeverOverwrites:
    def test_second_create_keeps_original_question_rpc(self, client, as_student, fake_supabase, monkeypatch):
        _enable_rpc(fake_supabase, monkeypatch)
        first = client.post(
            "/chat-sessions",
            json={"content_id": "content-soc1-b", "initial_question_text": "PERGUNTA ORIGINAL"},
        )
        assert first.status_code in (200, 201), first.text
        first_id = first.json()["id"]

        # Same pair, different question → resumed (same id), original intact.
        second = client.post(
            "/chat-sessions",
            json={"content_id": "content-soc1-b", "initial_question_text": "PERGUNTA DIFERENTE"},
        )
        assert second.status_code in (200, 201), second.text
        assert second.json()["id"] == first_id, "must resume the SAME session"
        assert second.json()["initial_question_text"] == "PERGUNTA ORIGINAL"

        # Exactly one row for the pair; storage never mutated to the new question.
        rows = [
            r for r in fake_supabase.rows("chat_sessions")
            if r["content_id"] == "content-soc1-b" and r["user_id"] == STUDENT_A_ID
        ]
        assert len(rows) == 1
        assert rows[0]["initial_question_text"] == "PERGUNTA ORIGINAL"

    def test_legacy_null_is_backfilled_once_then_frozen(self, client, as_student, fake_supabase):
        # A pre-SOC-1 active session (NULL question) is backfilled on the first
        # resume that carries a question, then frozen against later overwrites.
        fake_supabase.add("chat_sessions", {
            "id": "legacy-sess", "user_id": STUDENT_A_ID, "content_id": "content-legacy",
            "status": "active", "total_messages": 2, "initial_question_text": None,
        })
        r1 = client.post(
            "/chat-sessions",
            json={"content_id": "content-legacy", "initial_question_text": "BACKFILL"},
        )
        assert r1.status_code in (200, 201), r1.text
        assert r1.json()["id"] == "legacy-sess"
        assert r1.json()["initial_question_text"] == "BACKFILL"

        # A later resume with a different question does NOT overwrite the backfill.
        r2 = client.post(
            "/chat-sessions",
            json={"content_id": "content-legacy", "initial_question_text": "OUTRA"},
        )
        assert r2.json()["initial_question_text"] == "BACKFILL"


# ---------------------------------------------------------------------------
# (c) by-content surfaces the stored question
# ---------------------------------------------------------------------------
class TestByContentSurfacesQuestion:
    def test_by_content_returns_initial_question_text(self, client, as_student, fake_supabase):
        q = "Qual a diferenca entre validade e verdade?"
        created = client.post(
            "/chat-sessions",
            json={"content_id": "content-soc1-c", "initial_question_text": q},
        )
        assert created.status_code in (200, 201), created.text

        resp = client.get("/chat-sessions/by-content/content-soc1-c")
        assert resp.status_code == 200, resp.text
        assert resp.json()["initial_question_text"] == q


# ---------------------------------------------------------------------------
# (d) completed → new attempt spawns a NEW session with the NEW question
# ---------------------------------------------------------------------------
class TestCompletedSpawnsNewSessionWithNewQuestion:
    def test_completed_then_new_question_creates_distinct_session(self, client, as_student, fake_supabase):
        # A completed session for the pair, carrying the OLD question.
        fake_supabase.add("chat_sessions", {
            "id": "done-sess", "user_id": STUDENT_A_ID, "content_id": "content-soc1-d",
            "status": "completed", "total_messages": 12,
            "initial_question_text": "PERGUNTA ANTIGA",
        })
        resp = client.post(
            "/chat-sessions",
            json={"content_id": "content-soc1-d", "initial_question_text": "PERGUNTA NOVA"},
        )
        assert resp.status_code in (200, 201), resp.text
        # A brand-new, distinct session (not the completed one) with the NEW question.
        assert resp.json()["id"] != "done-sess"
        assert resp.json()["status"] == "active"
        assert resp.json()["initial_question_text"] == "PERGUNTA NOVA"

        rows = [
            r for r in fake_supabase.rows("chat_sessions")
            if r["content_id"] == "content-soc1-d" and r["user_id"] == STUDENT_A_ID
        ]
        # SEC-CHAT-3: the completed row survives alongside the fresh attempt.
        assert len(rows) == 2
        by_status = {r["status"]: r["initial_question_text"] for r in rows}
        assert by_status["completed"] == "PERGUNTA ANTIGA"
        assert by_status["active"] == "PERGUNTA NOVA"
