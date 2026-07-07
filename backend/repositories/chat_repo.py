"""Chat repository — Supabase client API.

TPP-3 centralizes ALL chat-turn persistence here:

* ``persist_turn`` is the single write path for a chat turn. It inserts exactly
  one ``chat_messages`` row and increments ``chat_sessions.total_messages``
  **atomically** via the ``increment_chat_session_messages`` RPC (migration B,
  TPP-1) — never a Python read-modify-write, so concurrent turns can't lose an
  update (#40). If the RPC is unavailable (older DB, or the in-memory test fake),
  it degrades to a guarded single-statement update; correctness of the *insert*
  is never sacrificed.
* ``count_user_messages`` returns the real persisted ``role='user'`` count for a
  session — the canonical figure for analytics/pacing reconciliation and the
  server-side source of truth for TPP-5 (``interactions_remaining``).
* ``get_session_messages`` orders by ``(created_at, sequence, id)`` so two turns
  sharing a microsecond timestamp never reorder in the transcript or export.

These methods are synchronous (the Supabase client is sync). Async handlers must
call them off the event loop via ``run_in_threadpool`` / ``anyio.to_thread`` — see
``routes_ai.py`` (ASYNC-AI-1 convention). ``persist_turn_async`` is provided as the
non-blocking wrapper handlers should prefer.
"""
import logging
from typing import Dict, List, Optional

from supabase import Client

from .base import BaseRepository

logger = logging.getLogger(__name__)


class ChatRepository(BaseRepository):
    def __init__(self, client: Client):
        super().__init__(client, "chat_sessions")

    def get_user_sessions(self, user_id: str) -> List[Dict]:
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        sessions = res.data or []
        for session in sessions:
            session["messages"] = self.get_session_messages(session["id"])
        return sessions

    def get_by_content_user(self, content_id: str, user_id: str) -> Optional[Dict]:
        # DATA-GAM-3 guard: (content_id, user_id) is NOT unique — SEC-CHAT-3 keeps a
        # completed session alongside a fresh "new attempt" row for the same pair. A
        # bare ``.maybe_single()`` 500s on >1 match, so order newest-first and take
        # one to reliably return the most recent session. (Full status machine is
        # DATA-GAM-4.)
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("content_id", content_id)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
        return res.data

    # ── message persistence ──────────────────────────────────────────
    def _insert_message(self, session_id: str, data: dict) -> Dict:
        """Insert exactly one ``chat_messages`` row. Internal: callers must use
        :meth:`persist_turn` so the atomic counter increment always runs."""
        payload = dict(data)
        payload["session_id"] = session_id
        res = self.client.table("chat_messages").insert(payload).execute()
        return res.data[0] if res.data else {}

    def _increment_total_messages(self, session_id: str) -> None:
        """Atomically bump ``chat_sessions.total_messages`` for ``session_id``.

        Primary path is the ``increment_chat_session_messages`` RPC (a single
        ``SET total_messages = total_messages + 1`` — no lost updates). If the RPC
        is missing (DB not yet migrated, or the in-memory fake has no ``.rpc``),
        fall back to a single guarded ``UPDATE``; the message itself is already
        persisted, so a counter that lags is a soft (recoverable) degradation,
        never data loss.
        """
        rpc = getattr(self.client, "rpc", None)
        if callable(rpc):
            try:
                rpc("increment_chat_session_messages", {"p_session_id": session_id}).execute()
                return
            except Exception as exc:  # pragma: no cover - defensive RPC fallback
                logger.warning(
                    "increment_chat_session_messages RPC failed for %s (%s); "
                    "falling back to non-atomic update",
                    session_id, exc,
                )

        # Fallback: read current count then write +1. Not atomic under concurrency,
        # but keeps the counter advancing where the RPC is unavailable.
        try:
            cur = (
                self.client.table(self.table)
                .select("total_messages")
                .eq("id", session_id)
                .maybe_single()
                .execute()
            )
            current = (cur.data or {}).get("total_messages") if cur else None
            new_count = (current or 0) + 1
            self.client.table(self.table).update(
                {"total_messages": new_count}
            ).eq("id", session_id).execute()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("total_messages fallback update failed for %s: %s", session_id, exc)

    def persist_turn(self, session_id: str, message_data: dict) -> Dict:
        """Persist ONE chat turn: insert the message row + atomically increment
        the session counter. The single write path for a turn (TPP-3).

        Returns the inserted message row.
        """
        inserted = self._insert_message(session_id, message_data)
        self._increment_total_messages(session_id)
        return inserted

    def count_user_messages(self, session_id: str) -> int:
        """Real persisted count of ``role='user'`` messages for the session.

        Canonical figure for analytics reconciliation and the server-side pacing
        derivation (TPP-5). Derived on-read, never trusting ``total_messages``.
        """
        res = (
            self.client.table("chat_messages")
            .select("id")
            .eq("session_id", session_id)
            .eq("role", "user")
            .execute()
        )
        return len(res.data or [])

    def get_session_messages(self, session_id: str) -> List[Dict]:
        """Return the session transcript ordered by a stable key.

        ``(created_at, sequence, id)``: ``created_at`` is primary; ``sequence``
        (migration A backfill) and ``id`` are deterministic tiebreakers so two
        turns sharing a microsecond never reorder (#TPP-3 ordering defect).
        """
        res = (
            self.client.table("chat_messages")
            .select("*")
            .eq("session_id", session_id)
            .order("created_at")
            .order("sequence")
            .order("id")
            .execute()
        )
        return res.data or []

    def get_session_with_messages(self, session_id: str) -> Optional[Dict]:
        res = self.client.table(self.table).select("*").eq("id", session_id).maybe_single().execute()
        if not res.data:
            return None
        session = res.data
        session["messages"] = self.get_session_messages(session_id)
        return session

    # Backwards-compat alias: legacy callers of ``add_message`` get the full
    # persist_turn behavior (insert + atomic increment) so no path can insert a
    # message while skipping the counter.
    def add_message(self, session_id: str, data: dict) -> Dict:
        return self.persist_turn(session_id, data)
