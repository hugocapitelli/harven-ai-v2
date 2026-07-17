"""Token-usage repository — Supabase client API (TKN-2).

Thin data-access layer over the existing (previously orphan) ``token_usage``
table — one row per ``(user_id, usage_date)``, enforced by
``UNIQUE(user_id, usage_date)`` (see ``backend/models/integration.py`` /
``backend/supabase_schema.sql``). It replaces the volatile in-memory
``_user_token_cache`` in ``ai_service.py`` (bug #12) with durable, concurrency-safe
persistence; the actual wiring of ``check/track`` happens in TKN-3 — this story is
exclusively the repository and its contract.

Two operations:

* ``get_today_usage`` reads ``tokens_used`` for the user's row of the current
  server day via ``.maybe_single()``. Absence == ``0`` (never ``None``/exception),
  so callers can treat "no consumption yet today" as a plain zero.
* ``add_usage`` increments the daily counter **atomically** through the
  ``increment_token_usage`` RPC (migration of TKN-1): a single
  ``INSERT ... ON CONFLICT (user_id, usage_date) DO UPDATE SET tokens_used =
  tokens_used + EXCLUDED.tokens_used RETURNING tokens_used`` — the sum lives in
  Postgres, never a Python read-modify-write, so concurrent writes can't lose an
  increment. The RPC returns the new total, which we return directly. A
  non-positive ``tokens`` is a safe no-op. If the RPC is unavailable (older DB, or
  the in-memory test fake without ``.rpc``), it degrades to returning the current
  total rather than raising — correctness of the *read* path is never sacrificed.

These methods are synchronous (the Supabase client is sync). Async handlers must
call them off the event loop via ``run_in_threadpool`` / ``anyio.to_thread``.
"""
import logging
from datetime import date

from supabase import Client

from .base import BaseRepository

logger = logging.getLogger(__name__)


class TokenUsageRepository(BaseRepository):
    def __init__(self, client: Client):
        super().__init__(client, "token_usage")

    def get_today_usage(self, user_id: str, raise_on_error: bool = False) -> int:
        """Tokens consumed by ``user_id`` on the current server day.

        Returns ``0`` when no row exists for ``(user_id, today)`` — absence is
        zero consumption. The date is always ``date.today().isoformat()``
        (server-side), matching TKN-1's ``(user_id, usage_date)`` index/constraint.

        P2: by default a READ FAILURE also degrades to ``0`` (legacy contract kept
        for the internal ``add_usage`` fallbacks), but that made a broken
        persistence layer indistinguishable from "no consumption yet" — the budget
        enforcer's fail-open accounting never fired. Callers that must OBSERVE the
        failure (``AIService.check_token_budget``) pass ``raise_on_error=True`` to
        receive the exception instead of a silent zero.
        """
        try:
            res = (
                self.client.table(self.table)
                .select("tokens_used")
                .eq("user_id", user_id)
                .eq("usage_date", date.today().isoformat())
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            logger.warning("get_today_usage read failed for %s: %s", user_id, exc)
            if raise_on_error:
                raise
            return 0
        if not res or not res.data:
            return 0
        return res.data.get("tokens_used") or 0

    def add_usage(self, user_id: str, tokens: int) -> int:
        """Atomically add ``tokens`` to ``user_id``'s usage for today; return the
        new daily total.

        ``tokens <= 0`` is a safe no-op (no write) that returns the current total.
        Otherwise the ``increment_token_usage`` RPC (TKN-1) performs the atomic
        upsert + sum in Postgres and returns the post-increment ``tokens_used``,
        which we return directly. If the client exposes no ``.rpc`` (un-migrated DB
        or in-memory fake), degrade to the current total instead of raising.
        """
        if tokens <= 0:
            return self.get_today_usage(user_id)

        rpc = getattr(self.client, "rpc", None)
        if callable(rpc):
            try:
                res = rpc(
                    "increment_token_usage",
                    {
                        "p_user_id": user_id,
                        "p_usage_date": date.today().isoformat(),
                        "p_tokens": tokens,
                    },
                ).execute()
                if res is not None and res.data is not None:
                    return res.data
            except Exception as exc:  # pragma: no cover - defensive RPC fallback
                logger.warning(
                    "increment_token_usage RPC failed for %s (%s); "
                    "returning current total",
                    user_id, exc,
                )

        # No RPC available (un-migrated DB / fake): can't write atomically here,
        # so report the current persisted total rather than raise.
        return self.get_today_usage(user_id)
