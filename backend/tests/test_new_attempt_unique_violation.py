"""P0 fix 2 — "Nova tentativa" must not die on the one-active-per-pair unique index.

The DB enforces at most ONE ``active`` chat_session per ``(user_id, content_id)``
(partial unique index backing the TPP-2 ``upsert_chat_session`` RPC). The
create-or-get endpoint resolves only the NEWEST row for the pair; when that newest
row is ``completed`` it falls through to INSERT a fresh active attempt. But an
OLDER ``active`` row can survive hidden behind the completed one (GRD-2 phantom,
clock ties, races) — the insert then violates the index and "Refazer sessão" 500s.

Pinned here:
  * newest=completed + older stranded active → the endpoint RESUMES the stranded
    active attempt (no new row, no violation, completed history preserved);
  * a genuine DB unique violation on the insert (race path) is recovered by
    returning the surviving active row instead of a 500 — proven against a fake
    that actually ENFORCES the partial index;
  * the plain "Refazer" flow (only completed rows exist) still creates a fresh
    active attempt under the enforcing fake — the fix does not break refazer.
"""
from __future__ import annotations

import pytest

from conftest import STUDENT_A_ID, make_seed_tables
from fakes import FakeSupabaseClient


class ActiveUniqueIndexFake(FakeSupabaseClient):
    """FakeSupabaseClient that ENFORCES the production partial unique index:
    at most one ``status='active'`` chat_session per (user_id, content_id)."""

    def table(self, name):
        qb = super().table(name)
        if name != "chat_sessions":
            return qb
        orig_execute = qb.execute

        def execute():
            if qb._op == "insert":
                payloads = qb._payload if isinstance(qb._payload, list) else [qb._payload]
                for p in payloads:
                    if p.get("status") != "active":
                        continue
                    for r in self._tables.get("chat_sessions", []):
                        if (
                            r.get("status") == "active"
                            and r.get("user_id") == p.get("user_id")
                            and r.get("content_id") == p.get("content_id")
                        ):
                            raise Exception(
                                'duplicate key value violates unique constraint '
                                '"uq_chat_sessions_active" (SQLSTATE 23505)'
                            )
            return orig_execute()

        qb.execute = execute
        return qb


@pytest.fixture
def fake_supabase() -> ActiveUniqueIndexFake:
    """Module-level override of conftest's fixture: same seed, index enforced."""
    return ActiveUniqueIndexFake(make_seed_tables())


def _seed_pair(fake, content_id: str, *, stranded_active: bool):
    """Newest row completed; optionally an OLDER stranded active behind it."""
    if stranded_active:
        fake.add("chat_sessions", {
            "id": f"stranded-{content_id}", "user_id": STUDENT_A_ID,
            "content_id": content_id, "status": "active", "total_messages": 2,
            "initial_question_text": "PERGUNTA ORIGINAL",
            "created_at": "2026-01-01T00:00:00Z",
        })
    fake.add("chat_sessions", {
        "id": f"done-{content_id}", "user_id": STUDENT_A_ID,
        "content_id": content_id, "status": "completed", "total_messages": 6,
        "initial_question_text": "PERGUNTA ORIGINAL",
        "created_at": "2026-01-02T00:00:00Z",
    })


class TestStrandedActiveBehindCompleted:
    def test_resumes_stranded_active_instead_of_500(self, client, as_student, fake_supabase):
        _seed_pair(fake_supabase, "content-p0", stranded_active=True)

        resp = client.post(
            "/chat-sessions",
            json={"content_id": "content-p0", "initial_question_text": "PERGUNTA NOVA"},
        )
        assert resp.status_code in (200, 201), resp.text
        body = resp.json()
        assert body["id"] == "stranded-content-p0"
        assert body["status"] == "active"
        # SOC-1 first-write-wins: the stranded attempt keeps ITS question.
        assert body["initial_question_text"] == "PERGUNTA ORIGINAL"

        rows = [
            r for r in fake_supabase.rows("chat_sessions")
            if r["content_id"] == "content-p0"
        ]
        # No third row was created; the completed history survives untouched.
        assert len(rows) == 2
        assert any(r["id"] == "done-content-p0" and r["status"] == "completed" for r in rows)

    def test_direct_insert_race_recovers_surviving_active(self, fake_supabase):
        """Race path: even if the pre-check misses (concurrent create), the insert's
        unique violation is recovered by returning the surviving active row."""
        from routes_ai import _create_chat_session_row

        _seed_pair(fake_supabase, "content-race", stranded_active=True)
        row = _create_chat_session_row(
            fake_supabase, STUDENT_A_ID, "content-race", "PERGUNTA NOVA"
        )
        assert row["id"] == "stranded-content-race"
        assert row["status"] == "active"

    def test_non_unique_insert_errors_still_propagate(self, fake_supabase, monkeypatch):
        """Only unique/duplicate violations are recovered — an unrelated DB error
        must not be silently converted into a session resume."""
        from routes_ai import _create_chat_session_row

        class BrokenFake(ActiveUniqueIndexFake):
            def table(self, name):
                qb = FakeSupabaseClient.table(self, name)
                if name == "chat_sessions":
                    def boom():
                        raise Exception("connection reset by peer")
                    qb.execute = boom
                return qb

        broken = BrokenFake(make_seed_tables())
        with pytest.raises(Exception, match="connection reset"):
            _create_chat_session_row(broken, STUDENT_A_ID, "content-x", None)


class TestRefazerStillWorksUnderEnforcedIndex:
    def test_completed_only_pair_still_spawns_new_attempt(self, client, as_student, fake_supabase):
        """The canonical "Refazer" (only completed rows, no active) keeps creating a
        fresh distinct active session — the partial index allows it and the fix
        must not regress GRD-3/SEC-CHAT-3."""
        _seed_pair(fake_supabase, "content-refazer", stranded_active=False)

        resp = client.post(
            "/chat-sessions",
            json={"content_id": "content-refazer", "initial_question_text": "PERGUNTA NOVA"},
        )
        assert resp.status_code in (200, 201), resp.text
        body = resp.json()
        assert body["id"] != "done-content-refazer"
        assert body["status"] == "active"
        assert body["initial_question_text"] == "PERGUNTA NOVA"

        rows = [
            r for r in fake_supabase.rows("chat_sessions")
            if r["content_id"] == "content-refazer"
        ]
        assert sorted(r["status"] for r in rows) == ["active", "completed"]
