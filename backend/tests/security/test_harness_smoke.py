"""Harness smoke + IDOR sentinel tests (SEC-ADMIN-1) and the SEC-AUTHZ-0 reference.

Proves the in-process harness is wired correctly (no network, no DB):
  * the FastAPI app boots and `/health` answers through the fake Supabase client;
  * the deterministic seed is queryable through the fake's chained builder;
  * the 3-outcome IDOR helpers operate over a seeded fake;
  * the SEC-AUTHZ-0 reference usage in `create_or_get_chat_session` proves
    `body.user_id` is never trusted (the live pattern downstream stories follow).
"""
from __future__ import annotations

import pytest

from conftest import (
    SESSION_A_ID,
    STUDENT_A_ID,
    STUDENT_B_ID,
    NOTIFICATION_A_ID,
)
from idor_helpers import (
    assert_owner_passes,
    assert_cross_actor_forbidden_no_mutation,
    assert_body_user_id_ignored,
)


# ---------------------------------------------------------------------------
# Smoke — the harness itself
# ---------------------------------------------------------------------------
def test_health_smoke(client):
    """The app boots and /health answers via the fake client (no real DB)."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"


def test_seed_is_queryable_through_fake(fake_supabase):
    """The chained builder resolves the deterministic seed without a DB."""
    res = (
        fake_supabase.table("chat_sessions")
        .select("*")
        .eq("id", SESSION_A_ID)
        .maybe_single()
        .execute()
    )
    assert res.data is not None
    assert res.data["user_id"] == STUDENT_A_ID

    missing = (
        fake_supabase.table("chat_sessions")
        .select("*")
        .eq("id", "nope")
        .maybe_single()
        .execute()
    )
    assert missing.data is None


def test_fake_write_chains_are_audited(fake_supabase):
    """insert/update/delete land in the in-memory table and the mutation log."""
    fake_supabase.table("notifications").insert(
        {"id": "n-new", "user_id": STUDENT_A_ID, "title": "x"}
    ).execute()
    assert fake_supabase.find("notifications", id="n-new") is not None

    fake_supabase.table("notifications").update({"read": True}).eq("id", "n-new").execute()
    assert fake_supabase.find("notifications", id="n-new")["read"] is True

    ops = {m["op"] for m in fake_supabase.mutations}
    assert {"insert", "update"} <= ops


# ---------------------------------------------------------------------------
# Sentinel — owner-vs-cross-actor over a seeded notification
# ---------------------------------------------------------------------------
def test_idor_helpers_owner_vs_cross_actor_pattern(fake_supabase):
    """Sentinel demonstrating the dono-vs-ator-cruzado contract on `notifications`.

    Simulates the decision an endpoint must make: only the owner may mutate their
    notification; a cross actor must be blocked with no write to the victim row.
    """
    from fastapi import HTTPException
    import authz

    notif = fake_supabase.find("notifications", id=NOTIFICATION_A_ID)
    owner = {"id": STUDENT_A_ID, "role": "STUDENT"}
    stranger = {"id": STUDENT_B_ID, "role": "STUDENT"}

    # Owner: decision passes, then a legitimate write lands.
    authz.assert_owner_or_role(notif["user_id"], owner, "ADMIN")
    fake_supabase.reset_mutations()
    fake_supabase.table("notifications").update({"read": True}).eq("id", NOTIFICATION_A_ID).execute()

    class _OkResp:
        status_code = 200
        text = ""
    assert_owner_passes(_OkResp())

    # Cross actor: the decision raises 403 BEFORE any write happens.
    fake_supabase.reset_mutations()
    with pytest.raises(HTTPException) as exc:
        authz.assert_owner_or_role(notif["user_id"], stranger, "ADMIN")
    assert exc.value.status_code == 403

    class _ForbiddenResp:
        status_code = 403
        text = "forbidden"
    assert_cross_actor_forbidden_no_mutation(
        _ForbiddenResp(), fake_supabase, table="notifications", victim_row_id=NOTIFICATION_A_ID
    )


# ---------------------------------------------------------------------------
# SEC-AUTHZ-0 reference usage — create_or_get_chat_session ignores body.user_id
# ---------------------------------------------------------------------------
def test_reference_create_session_owner_passes(client, as_student, fake_supabase):
    """The authenticated student creating their own session succeeds and is owned by them."""
    resp = client.post("/chat-sessions", json={"content_id": "content-new"})
    assert_owner_passes(resp)
    assert resp.json()["user_id"] == STUDENT_A_ID


def test_reference_create_session_ignores_forged_body_user_id(client, as_student, fake_supabase):
    """A STUDENT planting another user's id in the body is rejected (spoof blocked).

    `create_or_get_chat_session` now calls `assert_owner_or_role(data.user_id, ...)`
    so a STUDENT forging `user_id=STUDENT_B` gets 403 and no session is created for
    the victim. This is the live proof of the SEC-AUTHZ-0 pattern.
    """
    def _call(payload):
        body = {"content_id": "content-spoof"}
        body.update(payload)
        return client.post("/chat-sessions", json=body)

    def _effective(resp):
        # On a 2xx the created row's user_id is the effective actor.
        return resp.json().get("user_id")

    assert_body_user_id_ignored(
        call=_call,
        authenticated_user_id=STUDENT_A_ID,
        forged_user_id=STUDENT_B_ID,
        effective_user_id_of=_effective,
    )

    # No session was created for the victim STUDENT_B with the spoofed content.
    leaked = fake_supabase.find("chat_sessions", user_id=STUDENT_B_ID, content_id="content-spoof")
    assert leaked is None


def test_reference_admin_may_set_body_user_id(client, as_admin, fake_supabase):
    """An ADMIN is allowed to act on another user's id (privileged override)."""
    resp = client.post("/chat-sessions", json={"content_id": "content-admin", "user_id": STUDENT_B_ID})
    # ADMIN passes the ownership gate; the route then uses the admin's own id for
    # the row (uid = current_user["id"]), so the spoof gate does not 403.
    assert resp.status_code in (200, 201)
