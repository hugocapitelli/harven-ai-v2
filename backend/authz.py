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


# ---------------------------------------------------------------------------
# Content-tree scoping (teacher -> course -> chapter -> content)
# ---------------------------------------------------------------------------
# EPIC-SEC / SEC-SCOPE-8. The discipline gate above only knows how to decide a
# ``discipline_id``, but the whole course/chapter/content CRUD in ``main.py``
# addresses rows by ``course_id`` / ``chapter_id`` / ``content_id``. These
# helpers walk the ownership chain ``content -> chapter -> course -> discipline``
# up to a ``discipline_id`` and then reuse the already-proven
# :func:`assert_teacher_owns_discipline` decision, so ADMIN bypass and the
# TEACHER/INSTRUCTOR scoping semantics stay in exactly one place.
#
# Same contract as the rest of this module:
#   * plain functions (ownership is decided AFTER the row is loaded, from the
#     loaded row's foreign key — never from a client-supplied body field);
#   * pure decision + single-purpose loaders: a missing row raises ``404`` (it
#     does not disclose whether the id exists for another teacher) and an actor
#     that fails the scope raises ``403`` before any mutation;
#   * ADMIN short-circuits *before* any load (platform-wide authority), matching
#     ``assert_teacher_owns_discipline``.
def _load_row_or_404(client: Any, table: str, row_id: str, detail: str) -> dict:
    """Load ``table`` row by id or raise ``404`` (mirrors ``load_session_or_404``)."""
    res = (
        client.table(table)
        .select("*")
        .eq("id", row_id)
        .maybe_single()
        .execute()
    )
    data = getattr(res, "data", None) if res is not None else None
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return data


def assert_teacher_owns_course(
    course_id: str,
    current_user: Mapping[str, Any],
    client: Any,
    repo: Any,
) -> dict:
    """Allow ADMIN, or a TEACHER/INSTRUCTOR scoped to the course's discipline.

    ``repo`` is a ``DisciplineRepository`` (same object accepted by
    :func:`assert_teacher_owns_discipline`); ``client`` is the Supabase client
    used to load the course row.

    Decision order:
      1. ADMIN bypasses before any load (platform-wide authority).
      2. The course is loaded; a missing course raises ``404``.
      3. A course with **no** ``discipline_id`` (legacy / orphaned row) is
         **denied** for non-ADMIN — fail-closed, since there is no discipline to
         scope the teacher against and we must never let an unrelated teacher
         mutate an unclaimed course.
      4. Otherwise the course's ``discipline_id`` is handed to
         :func:`assert_teacher_owns_discipline`, which allows only a teacher
         linked to that discipline.

    Returns the loaded course row so the caller can reuse it without a second
    fetch. Raises ``HTTPException`` (403/404) on deny.
    """
    if _role_of(current_user) == "ADMIN":
        # ADMIN still needs the row's existence enforced by the endpoint's own
        # loader; ownership is unconditional so we do not load here.
        return {}

    course = _load_row_or_404(client, "courses", course_id, "Curso nao encontrado")
    discipline_id = course.get("discipline_id")
    if not discipline_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissao insuficiente para este curso",
        )
    assert_teacher_owns_discipline(discipline_id, current_user, repo)
    return course


def assert_teacher_owns_chapter(
    chapter_id: str,
    current_user: Mapping[str, Any],
    client: Any,
    repo: Any,
) -> dict:
    """Allow ADMIN, or a TEACHER/INSTRUCTOR scoped to the chapter's course/discipline.

    Walks ``chapter -> course`` and defers the discipline decision to
    :func:`assert_teacher_owns_course`. A missing chapter raises ``404``.
    Returns the loaded chapter row. Raises ``HTTPException`` (403/404) on deny.
    """
    if _role_of(current_user) == "ADMIN":
        return {}

    chapter = _load_row_or_404(client, "chapters", chapter_id, "Capitulo nao encontrado")
    course_id = chapter.get("course_id")
    if not course_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissao insuficiente para este capitulo",
        )
    assert_teacher_owns_course(course_id, current_user, client, repo)
    return chapter


def assert_teacher_owns_content(
    content_id: str,
    current_user: Mapping[str, Any],
    client: Any,
    repo: Any,
) -> dict:
    """Allow ADMIN, or a TEACHER/INSTRUCTOR scoped to the content's chapter/course/discipline.

    Walks ``content -> chapter`` and defers to :func:`assert_teacher_owns_chapter`.
    A missing content raises ``404``. Returns the loaded content row. Raises
    ``HTTPException`` (403/404) on deny.
    """
    if _role_of(current_user) == "ADMIN":
        return {}

    content = _load_row_or_404(client, "contents", content_id, "Conteudo nao encontrado")
    chapter_id = content.get("chapter_id")
    if not chapter_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissao insuficiente para este conteudo",
        )
    assert_teacher_owns_chapter(chapter_id, current_user, client, repo)
    return content


def _is_teacher_actor(current_user: Mapping[str, Any]) -> bool:
    """True when the actor is a TEACHER/INSTRUCTOR (not ADMIN, not STUDENT)."""
    return _role_of(current_user) in DISCIPLINE_PRIVILEGED_ROLES


def enforce_teacher_scope_on_read(
    assertion: Any,
    resource_id: str,
    current_user: Mapping[str, Any],
    client: Any,
    repo: Any,
) -> None:
    """Apply a cross-teacher ownership gate to a shared (``get_current_user``) READ.

    Several course/chapter/content READ endpoints are reachable by *any*
    authenticated user (STUDENT enrollment scoping governs students elsewhere —
    ``test_courses_student_scope``). The cross-teacher leak on those reads is a
    TEACHER/INSTRUCTOR pulling *another* teacher's course tree. This helper closes
    exactly that hole without touching STUDENT or ADMIN paths:

      * TEACHER/INSTRUCTOR  -> the given ``assertion`` (one of
        :func:`assert_teacher_owns_course` / ``_chapter`` / ``_content`` /
        ``_question``) runs and raises 403/404 when they are out of scope.
      * ADMIN / STUDENT     -> untouched (ADMIN has platform authority; STUDENT
        access is scoped by their enrollment, not by teacher-ownership).

    ``assertion`` is passed in (rather than branching on the resource kind here)
    so every call-site stays explicit about which chain it walks.
    """
    if _is_teacher_actor(current_user):
        assertion(resource_id, current_user, client, repo)


def assert_teacher_owns_question(
    question_id: str,
    current_user: Mapping[str, Any],
    client: Any,
    repo: Any,
) -> dict:
    """Allow ADMIN, or a TEACHER/INSTRUCTOR scoped to the question's content chain.

    Walks ``question -> content`` and defers to :func:`assert_teacher_owns_content`.
    A missing question raises ``404``. Returns the loaded question row. Raises
    ``HTTPException`` (403/404) on deny.
    """
    if _role_of(current_user) == "ADMIN":
        return {}

    question = _load_row_or_404(client, "questions", question_id, "Questao nao encontrada")
    content_id = question.get("content_id")
    if not content_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permissao insuficiente para esta questao",
        )
    assert_teacher_owns_content(content_id, current_user, client, repo)
    return question
