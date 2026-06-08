"""DB-backed active JWT signing secret provider (EPIC-SEC SEC-ROT-1).

The JWT signing secret used to live only in an env var with a public default
(``change-me-in-production``), and admin "force logout" tried to rotate it by
rewriting ``.env`` — silently ignored because docker-compose injects env vars
that outrank the ``.env`` file in pydantic-settings precedence (bugs #3 / #22).

This module makes the **database** (``system_settings.jwt_secret``) the durable
source of truth for the active signing secret, so it can be rotated in place
(SEC-ROT-3) and take effect without a restart.

Design contract (consumed by SEC-ROT-2 sign/verify and SEC-ROT-3 rotation —
do not break):

* ``get_active_jwt_secret(client)`` returns the active secret string. On a NULL
  column it **seeds** the row from the bootstrap env (``settings.JWT_SECRET_KEY``)
  and persists it, stamping ``jwt_secret_rotated_at``. Subsequent calls read the
  DB value.
* An **in-process cache with TTL** (``settings.JWT_SECRET_CACHE_TTL``, default 30s)
  avoids a query per request. After the TTL the value is re-read, so a rotation
  via ``force_logout`` propagates within ≤ TTL even without explicit invalidation.
* ``invalidate_jwt_secret_cache()`` drops the cache eagerly so the *next* call
  re-reads the DB immediately (used by SEC-ROT-3 right after a rotation).
* **Fail-closed:** on a DB read error we fall back to the bootstrap env secret,
  but a secret that is empty / a known weak default / shorter than the minimum
  length is **never** returned — it raises instead, so no token is ever signed
  with a publicly known key.

This module depends only on a duck-typed Supabase client and ``config``; it never
imports ``auth.py`` / ``main.py`` / ``routes_admin.py`` (no import cycles).
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

from config import MIN_JWT_SECRET_LENGTH, WEAK_JWT_SECRETS, get_settings

logger = logging.getLogger("harven")

# ---------------------------------------------------------------------------
# Process-local cache (secret, fetched_at_monotonic)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_cached_secret: Optional[str] = None
_cached_at: float = 0.0


class WeakJWTSecretError(RuntimeError):
    """Raised when no strong active secret can be resolved (fail-closed)."""


def _is_strong(secret: Optional[str]) -> bool:
    """A secret is strong iff it is non-empty, not a known default, and long enough."""
    if not secret:
        return False
    if secret in WEAK_JWT_SECRETS:
        return False
    return len(secret) >= MIN_JWT_SECRET_LENGTH


def _bootstrap_secret_or_raise() -> str:
    """Return the bootstrap env secret, or raise if it is weak (fail-closed)."""
    secret = get_settings().JWT_SECRET_KEY or ""
    if _is_strong(secret):
        return secret
    raise WeakJWTSecretError(
        "No strong JWT secret available: the DB column is unreadable/NULL and the "
        "bootstrap JWT_SECRET_KEY is empty, a known default, or shorter than "
        f"{MIN_JWT_SECRET_LENGTH} chars. Refusing to sign/verify with a public key."
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _settings_row(client: Any) -> Optional[dict]:
    """Return the singleton ``system_settings`` row, or None when absent."""
    res = (
        client.table("system_settings")
        .select("*")
        .limit(1)
        .maybe_single()
        .execute()
    )
    return getattr(res, "data", None) if res is not None else None


def _seed_secret(client: Any, row: Optional[dict]) -> str:
    """Persist the bootstrap secret into ``system_settings.jwt_secret`` (idempotent).

    Only called when the column is NULL. If no settings row exists yet, one is
    created. The value written is the (validated-strong) bootstrap env secret.
    Returns the seeded secret.
    """
    secret = _bootstrap_secret_or_raise()
    payload = {"jwt_secret": secret, "jwt_secret_rotated_at": _now_iso()}

    if row and row.get("id") is not None:
        # Idempotent: only seed when still NULL, so concurrent first-boots don't
        # clobber an already-seeded value.
        (
            client.table("system_settings")
            .update(payload)
            .eq("id", row["id"])
            .execute()
        )
    else:
        new_row = {"platform_name": "Harven.AI", **payload}
        client.table("system_settings").insert(new_row).execute()
    return secret


def get_active_jwt_secret(client: Any) -> str:
    """Return the active JWT signing secret (DB-backed, cached, fail-closed).

    Resolution order:
      1. Fresh in-process cache (within TTL) → return it.
      2. Read ``system_settings.jwt_secret``:
         - present & strong → cache + return.
         - NULL → seed from bootstrap env, persist, cache + return.
      3. On any DB error → fall back to the bootstrap env secret (validated
         strong), without caching the fallback.

    Never returns a weak/empty/default secret: a weak resolved value raises
    :class:`WeakJWTSecretError` instead of degrading to a public key.
    """
    global _cached_secret, _cached_at

    ttl = get_settings().JWT_SECRET_CACHE_TTL
    now = time.monotonic()

    with _lock:
        if _cached_secret is not None and (now - _cached_at) < ttl:
            return _cached_secret

    try:
        row = _settings_row(client)
        secret = (row or {}).get("jwt_secret")
        if not secret:
            secret = _seed_secret(client, row)
    except WeakJWTSecretError:
        # Bootstrap is also weak — propagate (fail-closed); never return a default.
        raise
    except Exception as exc:  # noqa: BLE001 — DB unreachable etc.
        logger.warning(
            "JWT secret DB read failed (%s); falling back to bootstrap env secret.",
            exc.__class__.__name__,
        )
        # Fail-closed fallback: bootstrap must itself be strong, else raise.
        return _bootstrap_secret_or_raise()

    if not _is_strong(secret):
        # A DB value that is somehow weak must not be used.
        raise WeakJWTSecretError(
            "Active JWT secret resolved from the DB is weak (empty, a known "
            "default, or too short). Refusing to sign/verify with a public key."
        )

    with _lock:
        _cached_secret = secret
        _cached_at = time.monotonic()
    return secret


def seed_jwt_secret(client: Any) -> None:
    """Idempotently ensure ``system_settings.jwt_secret`` is populated (startup seed).

    Thin wrapper over :func:`get_active_jwt_secret` for use in the app lifespan
    (SEC-ROT-2). Tolerant of DB failure at the call site — callers decide whether
    a failure should abort boot; this never silently signs with a weak key.
    """
    get_active_jwt_secret(client)


def invalidate_jwt_secret_cache() -> None:
    """Drop the cached secret so the next call re-reads the DB (used by SEC-ROT-3)."""
    global _cached_secret, _cached_at
    with _lock:
        _cached_secret = None
        _cached_at = 0.0
