"""Centralized authorization / ownership barrier for Harven.AI (EPIC-SEC).

The application layer is the **only** authorization barrier in this system:
there is no RLS in the schema and the shared Supabase client decodes to
``service_role`` (it bypasses RLS entirely). Every IDOR remediation story in
EPIC-SEC Fase 2 (SEC-CHAT-*, SEC-ADMIN-*, SEC-SCOPE-*) **imports** the helpers
defined here — ownership logic must never be redefined inline in the routes or
duplicated into ``auth.py``.

Design contract (stable — consumed by ~10 downstream stories, do not break):

* Helpers are **plain functions**, not FastAPI ``Depends``. Ownership can only
  be decided *after* the resource row is loaded (we don't know the owner until
  then), so the decision has to run *inside* the handler.
* Helpers are **pure decisions**: they either return normally (allow) or raise
  ``HTTPException`` (deny). They never read or mutate state beyond the explicit
  loader (``load_session_or_404``), so a denied actor causes no side-effects.
* ``body.user_id`` (or any client-supplied identity) is **never** a source of
  truth: the effective actor is always ``current_user``, and ownership is always
  checked against the *loaded* resource row — never against a body field.
* Privileged roles (ADMIN / TEACHER / INSTRUCTOR) are matched case-insensitively,
  mirroring the semantics of ``auth.require_role``.

This module depends only on ``fastapi.HTTPException`` and a duck-typed Supabase
client; it never imports from ``routes_ai.py`` / ``main.py`` (no import cycles).
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional

from fastapi import HTTPException, status

# ---------------------------------------------------------------------------
# Canonical privileged roles
# ---------------------------------------------------------------------------
# The set of roles that may override ownership across the platform. Kept here as
# the single source of truth so SEC-CHAT-* and SEC-ADMIN-* stay consistent.
# Stored upper-cased; all comparisons are case-insensitive.
PRIVILEGED_ROLES: frozenset[str] = frozenset({"ADMIN", "TEACHER", "INSTRUCTOR"})

# Roles that may manage / read across an entire discipline (teacher scoping).
# ADMIN is handled as an unconditional bypass in ``assert_teacher_owns_discipline``.
DISCIPLINE_PRIVILEGED_ROLES: frozenset[str] = frozenset({"TEACHER", "INSTRUCTOR"})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _role_of(current_user: Mapping[str, Any]) -> str:
    """Return the current user's role, upper-cased and stripped (never None)."""
    return str((current_user or {}).get("role") or "").strip().upper()


def _id_of(current_user: Mapping[str, Any]) -> Optional[str]:
    """Return the authenticated user's id (the only trusted identity)."""
    uid = (current_user or {}).get("id")
    return str(uid) if uid is not None else None


def _normalize_roles(roles: Iterable[str]) -> set[str]:
    return {str(r).strip().upper() for r in roles if str(r).strip()}


# ---------------------------------------------------------------------------
# Ownership / role decisions (pure functions — raise on deny, return on allow)
# ---------------------------------------------------------------------------
def assert_owner_or_role(
    resource_owner_id: Optional[str],
    current_user: Mapping[str, Any],
    *allowed_roles: str,
) -> None:
    """Allow the resource owner or any actor holding one of ``allowed_roles``.

    Decision order:
      1. The authenticated owner passes (``resource_owner_id == current_user["id"]``).
      2. Otherwise, an actor whose role is in ``allowed_roles`` (case-insensitive)
         passes — this is the TEACHER/ADMIN/INSTRUCTOR override.
      3. Everyone else (e.g. an unrelated STUDENT) is rejected with ``403`` before
         any side-effect, because this function only *decides*.

    The owner identity is always taken from ``current_user`` (the authenticated
    JWT subject), never from a request body, so a forged ``body.user_id`` cannot
    promote a cross-user actor to "owner".

    Raises:
        HTTPException: ``403 Forbidden`` when the actor is neither owner nor a
            privileged role.
    """
    actor_id = _id_of(current_user)

    # (1) Owner path — compare against the loaded resource, not any body field.
    if resource_owner_id is not None and actor_id is not None:
        if str(resource_owner_id) == str(actor_id):
            return

    # (2) Privileged-role override.
    allowed = _normalize_roles(allowed_roles)
    if allowed and _role_of(current_user) in allowed:
        return

    # (3) Deny — no read/mutation has occurred; this is a pure decision.
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permissao insuficiente",
    )


def require_self_or_role(
    path_user_id: Optional[str],
    current_user: Mapping[str, Any],
    *allowed_roles: str,
) -> None:
    """Allow only the user acting on their own ``user_id`` path, or a privileged role.

    Used by endpoints shaped like ``/users/{user_id}/...`` where the path segment
    identifies the *target* user. A STUDENT may only operate on their own
    ``user_id``; ADMIN/TEACHER/INSTRUCTOR (whatever is passed in ``allowed_roles``)
    may operate cross-user.

    This is intentionally identical in spirit to :func:`assert_owner_or_role`,
    specialised for the "path identifies the owner" shape so call-sites read
    clearly. The trusted identity is still ``current_user["id"]`` — never the
    path or the body when they conflict with authorization.

    Raises:
        HTTPException: ``403 Forbidden`` when the actor is neither the target user
            nor a privileged role.
    """
    assert_owner_or_role(path_user_id, current_user, *allowed_roles)


# ---------------------------------------------------------------------------
# Resource loaders (single-purpose; raise 404 on missing row)
# ---------------------------------------------------------------------------
def load_session_or_404(client: Any, session_id: str) -> dict:
    """Load a ``chat_sessions`` row by id, or raise ``404`` when absent.

    Mirrors the ``.maybe_single().execute()`` + ``res.data is None`` pattern used
    by ``auth.get_current_user``. Returning the row (rather than a bool) lets the
    caller pass ``row["user_id"]`` straight into :func:`assert_owner_or_role`,
    so a single load serves both existence and ownership checks.

    Returning ``404`` (not ``403``) for a missing row is deliberate: it does not
    disclose whether the id exists for another user.

    Raises:
        HTTPException: ``404 Not Found`` when no session matches ``session_id``.
    """
    res = (
        client.table("chat_sessions")
        .select("*")
        .eq("id", session_id)
        .maybe_single()
        .execute()
    )
    data = getattr(res, "data", None) if res is not None else None
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sessao nao encontrada")
    return data


# ---------------------------------------------------------------------------
# Discipline scoping (teacher -> discipline)
# ---------------------------------------------------------------------------
def assert_teacher_owns_discipline(
    discipline_id: str,
    current_user: Mapping[str, Any],
    repo: Any,
) -> None:
    """Allow ADMIN unconditionally, or a TEACHER/INSTRUCTOR scoped to ``discipline_id``.

    ``repo`` is a ``DisciplineRepository`` (or any object exposing
    ``get_teacher_discipline_ids(teacher_id) -> list[str]``). The teacher's set of
    disciplines is derived from the authenticated ``current_user["id"]`` — never
    from a body field — and ``discipline_id`` must be a member of it.

    Decision order:
      1. ADMIN bypasses (platform-wide authority).
      2. A TEACHER/INSTRUCTOR whose discipline set contains ``discipline_id`` passes.
      3. Everyone else is rejected with ``403``.

    Raises:
        HTTPException: ``403 Forbidden`` when the actor is not ADMIN and does not
            own the discipline.
    """
    role = _role_of(current_user)

    # (1) ADMIN bypass.
    if role == "ADMIN":
        return

    # (2) Teacher/instructor scoped to this discipline.
    if role in DISCIPLINE_PRIVILEGED_ROLES:
        teacher_id = _id_of(current_user)
        if teacher_id is not None:
            owned_ids = repo.get_teacher_discipline_ids(teacher_id) or []
            if str(discipline_id) in {str(i) for i in owned_ids}:
                return

    # (3) Deny.
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Permissao insuficiente para esta disciplina",
    )
