"""Prod incident 2026-07-17 — transcript reads 500 when ``chat_messages.sequence``
is missing (migration ``20260603a_dedupe_backfill.sql`` never applied).

Symptom (jeferson.aluno, production): "Chat resume error: AxiosError 500" on
``GET /chat-sessions/{id}/messages`` (and the same 500 on ``GET
/chat-sessions/{id}``) while ``by-content`` / ``by-user`` return 200 — the panel
shows the session as "Concluído 3/3" with an EMPTY transcript. Confirmed against
the production PostgREST directly:

    order=created_at.asc,sequence.asc,id.asc
    -> {"code":"42703", "message":"column chat_messages.sequence does not exist"}

Writes never reference ``sequence`` (the session accumulated 28 rows) and
``count_user_messages`` selects only ``id`` — so counting/pacing worked while
every transcript READ raised ``APIError`` → HTTP 500. Root cause: migrations are
applied by hand in the Supabase SQL Editor and the older 20260603a file (which
ADDs the column) was skipped, while the deployed code orders by
``(created_at, sequence, id)`` unconditionally.

Fix under test: ``ChatRepository.get_session_messages`` catches the 42703
undefined-column APIError and retries ordered by ``(created_at, id)`` — the same
deterministic key the migration's backfill uses — so an un-migrated DB degrades
to a correct transcript instead of a 500. Any other APIError still propagates.

The fake gained schema fidelity for this: ``mark_missing_column`` makes an
ORDER BY on the missing column raise the real ``postgrest`` 42703 APIError.
"""
from __future__ import annotations

import pytest
from postgrest.exceptions import APIError

from conftest import SESSION_A_ID


@pytest.fixture
def unmigrated_chat_messages(fake_supabase):
    """Simulate the production DB: ``chat_messages.sequence`` was never created."""
    fake_supabase.mark_missing_column("chat_messages", "sequence")
    # A second turn out of insertion order proves the fallback still sorts by
    # (created_at, id) instead of returning rows however they were stored.
    fake_supabase.add("chat_messages", {
        "id": "msg-a0", "session_id": SESSION_A_ID, "role": "assistant",
        "content": "seed question", "created_at": "2025-12-31T00:00:00Z",
    })
    return fake_supabase


class TestTranscriptReadsSurviveMissingSequenceColumn:
    def test_get_messages_returns_200_ordered_not_500(
        self, client, as_student, unmigrated_chat_messages
    ):
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}/messages")
        assert resp.status_code == 200, (
            f"transcript read on an un-migrated DB must degrade, not 500 — "
            f"got {resp.status_code}: {resp.text}"
        )
        rows = resp.json()
        assert [r["id"] for r in rows] == ["msg-a0", "msg-a1"]  # (created_at, id)

    def test_get_session_embeds_messages_not_500(
        self, client, as_student, unmigrated_chat_messages
    ):
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [m["id"] for m in body["messages"]] == ["msg-a0", "msg-a1"]

    def test_migrated_db_still_orders_by_sequence(self, client, as_student, fake_supabase):
        # Regression guard: with the column present, the (created_at, sequence, id)
        # key must remain the primary order — the fallback is for 42703 ONLY.
        fake_supabase.add("chat_messages", {
            "id": "msg-a2", "session_id": SESSION_A_ID, "role": "assistant",
            "content": "tie", "created_at": "2026-01-01T00:00:00Z", "sequence": 0,
        })
        # msg-a1 shares the timestamp; sequence breaks the tie in favor of msg-a2.
        for row in fake_supabase._tables["chat_messages"]:
            if row["id"] == "msg-a1":
                row["sequence"] = 1
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}/messages")
        assert resp.status_code == 200, resp.text
        assert [r["id"] for r in resp.json()] == ["msg-a2", "msg-a1"]

    def test_other_apierrors_still_propagate(self, unmigrated_chat_messages):
        # The fallback must be surgical: a non-42703 APIError (e.g. RLS/permission
        # 42501) on the ordered read is NOT swallowed into a silent retry.
        from repositories.chat_repo import ChatRepository

        class _Boom:
            def table(self, _name):
                raise APIError({
                    "code": "42501", "message": "permission denied",
                    "details": None, "hint": None,
                })

        with pytest.raises(APIError):
            ChatRepository(_Boom()).get_session_messages(SESSION_A_ID)
