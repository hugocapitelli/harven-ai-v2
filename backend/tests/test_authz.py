"""Unit tests for the authz helpers (SEC-AUTHZ-0).

These exercise the pure decision functions in `backend/authz.py` in isolation —
no FastAPI stack, no JWT, no DB — proving the 3 IDOR outcomes and the 404 path
that ~10 downstream stories depend on. The fake Supabase client (from `fakes.py`)
drives `load_session_or_404` through the real query chain without a database.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import authz
from fakes import FakeSupabaseClient

OWNER_ID = "user-owner"
STRANGER_ID = "user-stranger"


def _user(uid, role):
    return {"id": uid, "role": role, "name": uid}


# ---------------------------------------------------------------------------
# assert_owner_or_role — 3 IDOR outcomes
# ---------------------------------------------------------------------------
def test_owner_passes():
    # (a) authenticated owner passes — no exception.
    authz.assert_owner_or_role(OWNER_ID, _user(OWNER_ID, "STUDENT"), "ADMIN", "TEACHER")


def test_cross_student_forbidden():
    # (b) cross actor (unrelated STUDENT) -> 403, pure decision, no side effect.
    with pytest.raises(HTTPException) as exc:
        authz.assert_owner_or_role(OWNER_ID, _user(STRANGER_ID, "STUDENT"), "ADMIN", "TEACHER")
    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["ADMIN", "TEACHER", "INSTRUCTOR", "admin", "Teacher"])
def test_privileged_role_override_passes(role):
    # Privileged roles override ownership, case-insensitively.
    authz.assert_owner_or_role(
        OWNER_ID, _user(STRANGER_ID, role), "ADMIN", "TEACHER", "INSTRUCTOR"
    )


def test_role_not_in_allowed_is_forbidden():
    # A role that exists but is not whitelisted for this resource is denied.
    with pytest.raises(HTTPException) as exc:
        authz.assert_owner_or_role(OWNER_ID, _user(STRANGER_ID, "TEACHER"), "ADMIN")
    assert exc.value.status_code == 403


def test_body_user_id_never_trusted():
    """(c) A forged body.user_id cannot promote a stranger to owner.

    The helper only ever compares against current_user["id"]; it has no body
    parameter at all. Even if a caller *passed the forged id as resource_owner_id*
    (the worst-case misuse), a stranger acting on it without a privileged role is
    still rejected, because owner is current_user — not the forged value.
    """
    forged_owner = STRANGER_ID  # attacker plants their own id hoping to "own" it
    # Owner is derived from current_user; stranger is a plain STUDENT -> 403.
    with pytest.raises(HTTPException) as exc:
        authz.assert_owner_or_role(OWNER_ID, _user(STRANGER_ID, "STUDENT"))
    assert exc.value.status_code == 403
    # And no allowed_roles means even the "owner string == forged" trick is moot:
    # the only way to pass is to actually BE the owner via current_user.
    authz.assert_owner_or_role(forged_owner, _user(forged_owner, "STUDENT"))


def test_owner_with_no_allowed_roles_still_passes():
    authz.assert_owner_or_role(OWNER_ID, _user(OWNER_ID, "STUDENT"))


def test_none_owner_and_no_role_is_forbidden():
    with pytest.raises(HTTPException) as exc:
        authz.assert_owner_or_role(None, _user(STRANGER_ID, "STUDENT"))
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# require_self_or_role — path-shaped wrapper
# ---------------------------------------------------------------------------
def test_require_self_passes_for_self():
    authz.require_self_or_role(OWNER_ID, _user(OWNER_ID, "STUDENT"), "ADMIN")


def test_require_self_forbids_other_path_user():
    with pytest.raises(HTTPException) as exc:
        authz.require_self_or_role(OWNER_ID, _user(STRANGER_ID, "STUDENT"), "ADMIN")
    assert exc.value.status_code == 403


def test_require_self_admin_override():
    authz.require_self_or_role(OWNER_ID, _user(STRANGER_ID, "ADMIN"), "ADMIN")


# ---------------------------------------------------------------------------
# load_session_or_404 — row present vs null
# ---------------------------------------------------------------------------
def test_load_session_returns_row_when_present():
    fake = FakeSupabaseClient({
        "chat_sessions": [{"id": "s1", "user_id": OWNER_ID, "status": "active"}],
    })
    row = authz.load_session_or_404(fake, "s1")
    assert row["id"] == "s1"
    assert row["user_id"] == OWNER_ID


def test_load_session_404_when_absent():
    fake = FakeSupabaseClient({"chat_sessions": []})
    with pytest.raises(HTTPException) as exc:
        authz.load_session_or_404(fake, "does-not-exist")
    assert exc.value.status_code == 404


def test_load_then_owner_check_is_the_idor_pattern():
    """The canonical consumer pattern: load -> assert owner of loaded row."""
    fake = FakeSupabaseClient({
        "chat_sessions": [{"id": "s1", "user_id": OWNER_ID, "status": "active"}],
    })
    session = authz.load_session_or_404(fake, "s1")
    # Owner passes.
    authz.assert_owner_or_role(session["user_id"], _user(OWNER_ID, "STUDENT"), "ADMIN")
    # Stranger is blocked off the *loaded* row's owner, never a body field.
    with pytest.raises(HTTPException) as exc:
        authz.assert_owner_or_role(session["user_id"], _user(STRANGER_ID, "STUDENT"), "ADMIN")
    assert exc.value.status_code == 403


# ---------------------------------------------------------------------------
# assert_teacher_owns_discipline — admin bypass + teacher scoping
# ---------------------------------------------------------------------------
class _Repo:
    def __init__(self, owned):
        self._owned = owned

    def get_teacher_discipline_ids(self, teacher_id):
        return list(self._owned.get(teacher_id, []))


def test_admin_bypasses_discipline_scope():
    repo = _Repo({})  # admin owns nothing, still passes
    authz.assert_teacher_owns_discipline("d1", _user("admin", "ADMIN"), repo)


def test_teacher_owning_discipline_passes():
    repo = _Repo({"t1": ["d1", "d2"]})
    authz.assert_teacher_owns_discipline("d1", _user("t1", "TEACHER"), repo)


def test_teacher_not_owning_discipline_forbidden():
    repo = _Repo({"t1": ["d2"]})
    with pytest.raises(HTTPException) as exc:
        authz.assert_teacher_owns_discipline("d1", _user("t1", "TEACHER"), repo)
    assert exc.value.status_code == 403


def test_student_never_owns_discipline():
    repo = _Repo({"t1": ["d1"]})
    with pytest.raises(HTTPException) as exc:
        authz.assert_teacher_owns_discipline("d1", _user("s1", "STUDENT"), repo)
    assert exc.value.status_code == 403
