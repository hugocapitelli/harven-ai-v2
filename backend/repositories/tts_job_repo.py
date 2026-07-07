"""TTS job repository — Supabase client API (TTSJOB-1).

Thin data-access layer over the new durable `tts_jobs` table (migration
`20260707000001_tts_jobs.sql`), replacing the volatile in-memory `_tts_jobs` dict in
`routes_ai.py` (bug sweep #34/#58/#59). This story is exclusively the
persistence foundation — wiring the endpoints/worker to read/write through
this repository instead of the dict is a follow-up story.

Two contracts this repository exists to guarantee:

* **Ownership (IDOR guard, #58).** Every read is scoped by BOTH `content_id`
  and `user_id`. There is no method that returns a job by `content_id` alone —
  a caller with the wrong `user_id` gets `None`, never another user's row.
  `user_id` is always an explicit argument supplied by the caller (the
  authenticated identity); this repository never trusts a client-supplied
  body field.
* **TTL sweep never touches in-flight work (#59).** `sweep_expired` only
  considers rows whose `status` is terminal (`done`/`error`); a `processing`
  row — however old — is never selected, let alone deleted.

These methods are synchronous (the Supabase client is sync), matching every
other repository in this package.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from supabase import Client

from .base import BaseRepository

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ("done", "error")
VALID_AUDIO_TYPES = ("podcast", "summary", "explanation")


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Best-effort parse of a Postgres/PostgREST timestamptz string.

    Returns ``None`` (never raises) on missing/malformed input so a single
    unparsable row can't blow up the whole sweep — it is simply treated as
    "not expired" (kept), which is the safe failure mode.
    """
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


class TtsJobRepository(BaseRepository):
    def __init__(self, client: Client):
        super().__init__(client, "tts_jobs")

    # ── CREATE ───────────────────────────────────────────────────────
    def seed_processing(
        self,
        job_id: str,
        content_id: Optional[str],
        user_id: str,
        audio_type: str = "summary",
    ) -> Dict:
        """Idempotently create a job row in `processing` state.

        Calling this twice with the same `job_id` is safe: the second call is
        a no-op that returns the existing row unchanged (idempotency required
        by the Definition of Done — "semear o mesmo job duas vezes não cria
        duplicata nem corrompe estado").
        """
        existing = self.get_by_id(job_id)
        if existing is not None:
            return existing
        payload = {
            "id": job_id,
            "content_id": content_id,
            "user_id": user_id,
            "audio_type": audio_type,
            "status": "processing",
        }
        return self.create(payload)

    # ── UPDATE (lifecycle transitions) ──────────────────────────────
    def mark_done(
        self,
        job_id: str,
        audio_url: str,
        duration_estimate: Optional[str] = None,
    ) -> Optional[Dict]:
        """Transition a job to the terminal `done` state.

        Sets ``updated_at`` explicitly so ``sweep_expired``'s TTL measures age
        since COMPLETION, not since the row's original ``processing`` creation
        (a job that took a while to synthesize would otherwise look already
        stale the instant it finished).
        """
        payload: Dict[str, Any] = {
            "status": "done",
            "audio_url": audio_url,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if duration_estimate is not None:
            payload["duration_estimate"] = duration_estimate
        return self.update(job_id, payload)

    def mark_error(self, job_id: str, error: str) -> Optional[Dict]:
        """Transition a job to the terminal `error` state.

        Sets ``updated_at`` explicitly for the same reason as ``mark_done``.
        """
        return self.update(job_id, {
            "status": "error",
            "error": error[:500],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })

    # ── READ (ownership-scoped — IDOR guard) ────────────────────────
    def get_for_content(self, content_id: str, user_id: str) -> Optional[Dict]:
        """Return the job for `content_id` iff it belongs to `user_id`.

        Never filters on `content_id` alone. A cross-actor `user_id` (or a
        `content_id` that belongs to someone else) yields `None` — no row
        leak. `user_id` MUST be the authenticated caller's id, never a value
        read out of a request body.
        """
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("content_id", content_id)
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def get_active_for_content(
        self, content_id: str, audio_type: str, user_id: str
    ) -> Optional[Dict]:
        """Return the in-flight (`processing`) job for `(content_id, audio_type)`,
        scoped to `user_id`. Used to avoid dispatching a duplicate synthesis job
        for a style that is already being generated.
        """
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("content_id", content_id)
            .eq("user_id", user_id)
            .eq("audio_type", audio_type)
            .eq("status", "processing")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        return rows[0] if rows else None

    def count_active_for_user(self, user_id: str) -> int:
        """Count `processing` jobs owned by `user_id` (rate-limit/backpressure)."""
        res = (
            self.client.table(self.table)
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("status", "processing")
            .execute()
        )
        return res.count if res.count is not None else len(res.data or [])

    # ── SWEEP (TTL — terminal states only, #59) ─────────────────────
    def sweep_expired(self, ttl: timedelta, now: Optional[datetime] = None) -> List[Dict]:
        """Delete terminal (`done`/`error`) jobs older than `ttl`; return the
        deleted rows.

        `processing` jobs are NEVER considered by this method, regardless of
        age — the terminal-status filter is applied server-side (`.in_`)
        BEFORE any age comparison, so a bug in the date math can only ever
        fail to delete an expired terminal row, never delete an in-flight one.
        """
        now = now or datetime.now(timezone.utc)
        cutoff = now - ttl

        res = (
            self.client.table(self.table)
            .select("*")
            .in_("status", list(TERMINAL_STATUSES))
            .execute()
        )
        candidates = res.data or []

        expired_ids: List[str] = []
        expired_rows: List[Dict] = []
        for row in candidates:
            updated_at = _parse_timestamp(row.get("updated_at") or row.get("created_at"))
            if updated_at is None:
                # Can't determine age — safe default is to keep the row.
                continue
            if updated_at < cutoff:
                expired_ids.append(row["id"])
                expired_rows.append(row)

        for job_id in expired_ids:
            try:
                self.delete(job_id)
            except Exception as exc:  # pragma: no cover - defensive sweep guard
                logger.warning("sweep_expired: failed to delete tts_job %s: %s", job_id, exc)

        return expired_rows
