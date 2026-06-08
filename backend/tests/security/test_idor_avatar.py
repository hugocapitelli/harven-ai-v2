"""SEC-ADMIN-2 — IDOR on POST /users/{user_id}/avatar (3-outcome contract).

Bug #49: ``upload_avatar`` authenticated the caller but never compared the path
``user_id`` to ``current_user["id"]``, so any logged-in student could overwrite
any other account's ``avatar_url``.

The fix (authz ``require_self_or_role(user_id, current_user, "ADMIN")`` evaluated
*before* ``storage.save_file`` / ``user_repo.update``) must satisfy:

  (1) the owner uploading to their own id → 200, avatar updated;
  (2) a cross-user actor → 403, **no file written, no mutation** of the victim;
  (3) an ADMIN may upload to any id → 200.

We patch ``main.storage.save_file`` to a no-op URL so the 200 paths don't touch
the real filesystem; the 403 path must never reach it (asserted via a tripwire).
"""
from __future__ import annotations

import io

import pytest

from conftest import ADMIN_ID, STUDENT_A_ID, STUDENT_B_ID
from idor_helpers import (
    assert_cross_actor_forbidden_no_mutation,
    assert_owner_passes,
)

FAKE_AVATAR_URL = "/uploads/avatars/fake.png"


@pytest.fixture
def patched_storage(monkeypatch):
    """Replace storage.save_file with a no-op that records whether it ran."""
    import main

    state = {"called": False}

    async def _fake_save_file(file, subdir="general"):
        state["called"] = True
        return FAKE_AVATAR_URL

    monkeypatch.setattr(main.storage, "save_file", _fake_save_file)
    return state


def _png_upload():
    return {"file": ("a.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")}


# ---------------------------------------------------------------------------
# (1) Owner passes — student uploads to their own id
# ---------------------------------------------------------------------------
def test_upload_avatar_self_200(client, as_student, fake_supabase, patched_storage):
    resp = client.post(f"/users/{STUDENT_A_ID}/avatar", files=_png_upload())

    assert_owner_passes(resp)
    assert resp.json()["avatar_url"] == FAKE_AVATAR_URL
    assert patched_storage["called"] is True
    # The owner's row was actually updated.
    assert fake_supabase.find("users", id=STUDENT_A_ID)["avatar_url"] == FAKE_AVATAR_URL


# ---------------------------------------------------------------------------
# (2) Cross actor forbidden AND no mutation / no file write
# ---------------------------------------------------------------------------
def test_upload_avatar_cross_user_403_no_mutation(
    client, as_student, fake_supabase, patched_storage
):
    fake_supabase.reset_mutations()
    # STUDENT_A (the authenticated actor) targets STUDENT_B's id.
    resp = client.post(f"/users/{STUDENT_B_ID}/avatar", files=_png_upload())

    assert_cross_actor_forbidden_no_mutation(
        resp, fake_supabase, table="users", victim_row_id=STUDENT_B_ID
    )
    # The guard ran before any side-effect: storage was never touched.
    assert patched_storage["called"] is False
    # Victim's avatar is untouched (was unset, stays unset).
    assert fake_supabase.find("users", id=STUDENT_B_ID).get("avatar_url") is None


# ---------------------------------------------------------------------------
# (3) ADMIN is omnipotent — uploads to any id
# ---------------------------------------------------------------------------
def test_upload_avatar_admin_any_200(client, as_admin, fake_supabase, patched_storage):
    resp = client.post(f"/users/{STUDENT_B_ID}/avatar", files=_png_upload())

    assert_owner_passes(resp)
    assert resp.json()["avatar_url"] == FAKE_AVATAR_URL
    assert fake_supabase.find("users", id=STUDENT_B_ID)["avatar_url"] == FAKE_AVATAR_URL


# ---------------------------------------------------------------------------
# (4) Authorized but non-existent target → 404 (contract preserved)
# ---------------------------------------------------------------------------
def test_upload_avatar_admin_missing_target_404(
    client, as_admin, fake_supabase, patched_storage
):
    resp = client.post("/users/does-not-exist/avatar", files=_png_upload())
    assert resp.status_code == 404
