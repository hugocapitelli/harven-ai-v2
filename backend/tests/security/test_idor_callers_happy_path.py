"""Behavioural happy-path guard for the 4 real frontend callers (SEC-ADMIN-6).

The static signature guard (``test_idor_signature_guard``) proves every in-scope
route is *classified and wired* correctly, but it cannot prove ownership SEMANTICS
(the comparison lives in the handler body). This file closes that gap: it exercises
the actual HTTP behaviour of the four frontend-facing IDOR clusters and asserts the
3-outcome contract per caller, plus the ``body.user_id`` carve-out.

Frontend callers preserved (the legitimate flows that must keep working):
  * AccountSettings — avatar self-upload                 (SEC-ADMIN-2, bug #49)
  * Layout / AdminConsole — own notifications            (SEC-ADMIN-3, bug #16)
  * Gamification UI — student self-service               (SEC-ADMIN-4, bug #14)
  * SessionReview — owner/TEACHER read + reply           (SEC-ADMIN-5, bug #25)

3-outcome contract asserted for each:
  (1) authorized owner passes (2xx);
  (2) cross-tenant/cross-user actor → 403/404 AND no read/mutation on the victim;
  (3) ``body.user_id`` (or any client-supplied identity) is NEVER trusted — the
      effective actor derives from ``current_user``.

Runs fully in-process on the seeded ``FakeSupabaseClient`` (no network/DB). Shared
fixtures come from ``conftest.py``; assertions from ``idor_helpers``. ``conftest.py``
is never edited. This file is intentionally caller-centric and complements (does not
replace) the cluster-level suites in ``test_idor_admin.py`` / ``test_idor_chat.py``.
"""
from __future__ import annotations

import io

import pytest

from conftest import (
    ADMIN_ID,
    SESSION_A_ID,
    STUDENT_A_ID,
    STUDENT_B_ID,
    TEACHER_ID,
)
from idor_helpers import (
    assert_body_user_id_ignored,
    assert_cross_actor_forbidden_no_mutation,
    assert_owner_passes,
)

NOTIF_A = "notif-a"
NOTIF_B = "notif-b"
FAKE_AVATAR_URL = "/uploads/avatars/fake.png"


# ===========================================================================
# Shared helpers
# ===========================================================================
def _seed_notifications(fake):
    """Notifications carrying the ``is_read`` column the routes filter on."""
    fake.seed(
        "notifications",
        [
            {"id": NOTIF_A, "user_id": STUDENT_A_ID, "title": "A", "message": "m",
             "notification_type": "info", "link": None, "is_read": False},
            {"id": NOTIF_B, "user_id": STUDENT_B_ID, "title": "B", "message": "m",
             "notification_type": "info", "link": None, "is_read": False},
        ],
    )


@pytest.fixture
def patched_storage(monkeypatch):
    """No-op ``storage.save_file`` so 200 paths don't hit the filesystem and the
    403 path can be proven to never reach storage (the deny precedes side-effects)."""
    import main

    state = {"called": False}

    async def _fake_save_file(file, subdir="general"):
        state["called"] = True
        return FAKE_AVATAR_URL

    monkeypatch.setattr(main.storage, "save_file", _fake_save_file)
    return state


def _png():
    return {"file": ("a.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")}


# ===========================================================================
# Caller 1 — AccountSettings: avatar self-upload (bug #49 / SEC-ADMIN-2)
# ===========================================================================
class TestAvatarCaller:
    def test_owner_self_upload_passes(self, client, as_student, fake_supabase, patched_storage):
        resp = client.post(f"/users/{STUDENT_A_ID}/avatar", files=_png())
        assert_owner_passes(resp)
        assert fake_supabase.find("users", id=STUDENT_A_ID)["avatar_url"] == FAKE_AVATAR_URL

    def test_cross_actor_forbidden_no_file_no_mutation(self, client, as_student, fake_supabase, patched_storage):
        fake_supabase.reset_mutations()
        # STUDENT_A targets STUDENT_B.
        resp = client.post(f"/users/{STUDENT_B_ID}/avatar", files=_png())
        assert_cross_actor_forbidden_no_mutation(
            resp, fake_supabase, table="users", victim_row_id=STUDENT_B_ID
        )
        assert patched_storage["called"] is False  # gate ran before storage
        assert fake_supabase.find("users", id=STUDENT_B_ID).get("avatar_url") is None

    def test_admin_override_any_user_passes(self, client, as_admin, fake_supabase, patched_storage):
        resp = client.post(f"/users/{STUDENT_B_ID}/avatar", files=_png())
        assert_owner_passes(resp)


# ===========================================================================
# Caller 2 — Layout / AdminConsole: own notifications (bug #16 / SEC-ADMIN-3)
# ===========================================================================
class TestNotificationsCaller:
    def test_owner_reads_own_count(self, client, as_student, fake_supabase):
        _seed_notifications(fake_supabase)
        resp = client.get(f"/notifications/{STUDENT_A_ID}/count")
        assert_owner_passes(resp)
        assert resp.json()["unread"] == 1

    def test_owner_marks_own_read(self, client, as_student, fake_supabase):
        _seed_notifications(fake_supabase)
        resp = client.put(f"/notifications/{NOTIF_A}/read")
        assert_owner_passes(resp)
        assert fake_supabase.find("notifications", id=NOTIF_A)["is_read"] is True

    def test_cross_actor_cannot_mark_no_mutation(self, client, as_other_student, fake_supabase):
        _seed_notifications(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.put(f"/notifications/{NOTIF_A}/read")
        assert_cross_actor_forbidden_no_mutation(
            resp, fake_supabase, table="notifications", victim_row_id=NOTIF_A
        )
        assert fake_supabase.find("notifications", id=NOTIF_A)["is_read"] is False

    def test_cross_actor_cannot_read_count(self, client, as_other_student, fake_supabase):
        _seed_notifications(fake_supabase)
        resp = client.get(f"/notifications/{STUDENT_A_ID}/count")
        assert resp.status_code == 403
        assert "unread" not in resp.json()

    def test_admin_create_passes(self, client, as_admin, fake_supabase):
        resp = client.post("/notifications", json={"user_id": STUDENT_A_ID, "title": "oficial"})
        assert resp.status_code == 201

    def test_create_body_user_id_only_for_admin(self, client, as_student, fake_supabase):
        # (3) A STUDENT can never inject into another user's feed: create is ADMIN-only,
        # so the forged body.user_id is rejected outright (403), no insert lands.
        fake_supabase.reset_mutations()
        resp = client.post("/notifications", json={"user_id": STUDENT_B_ID, "title": "spam"})
        assert resp.status_code == 403
        assert all(m["table"] != "notifications" for m in fake_supabase.mutations)


# ===========================================================================
# Caller 3 — Gamification UI: student self-service (bug #14 / SEC-ADMIN-4)
# ===========================================================================
class TestGamificationCaller:
    def test_owner_self_activity_passes_points_from_server(self, client, as_student, fake_supabase):
        # Owner self-service passes; client-sent points are ignored (server whitelist).
        resp = client.post(
            f"/users/{STUDENT_A_ID}/activities",
            json={"activity_type": "content_completed", "points": 9999},
        )
        assert resp.status_code == 201
        assert resp.json()["points"] == 10  # not the forged 9999
        assert fake_supabase.find("user_activities", user_id=STUDENT_A_ID)["points"] == 10

    def test_cross_actor_cannot_write_activity(self, client, as_other_student, fake_supabase):
        fake_supabase.reset_mutations()
        resp = client.post(
            f"/users/{STUDENT_A_ID}/activities",
            json={"activity_type": "content_completed"},
        )
        assert resp.status_code == 403
        assert all(m["table"] not in ("user_activities", "user_stats") for m in fake_supabase.mutations)

    def test_body_user_id_never_redirects_self_service_write(self, client, as_student, fake_supabase):
        # (3) A STUDENT POSTs to their OWN path but forges body.user_id=STUDENT_B.
        # The write must land on the AUTHENTICATED user (STUDENT_A), never the forged id.
        def _call(payload):
            payload = dict(payload)
            payload.setdefault("activity_type", "content_completed")
            return client.post(f"/users/{STUDENT_A_ID}/activities", json=payload)

        def _effective(_resp):
            # The effective actor is the user_id the row was actually written to.
            row = fake_supabase.find("user_activities", activity_type="content_completed")
            return row.get("user_id") if row else None

        assert_body_user_id_ignored(
            call=_call,
            authenticated_user_id=STUDENT_A_ID,
            forged_user_id=STUDENT_B_ID,
            effective_user_id_of=_effective,
        )
        # And nothing was written under the forged victim id.
        assert fake_supabase.find("user_activities", user_id=STUDENT_B_ID) is None

    def test_admin_override_writes_for_other_user(self, client, as_admin, fake_supabase):
        resp = client.post(
            f"/users/{STUDENT_A_ID}/activities",
            json={"activity_type": "content_completed"},
        )
        assert resp.status_code == 201
        assert fake_supabase.find("user_activities", user_id=STUDENT_A_ID) is not None


# ===========================================================================
# Caller 4 — SessionReview: owner/TEACHER read + reply (bug #25 / SEC-ADMIN-5)
# ===========================================================================
class TestSessionReviewCaller:
    def _seed_review(self, fake, status="pending_student"):
        fake.seed(
            "session_reviews",
            [{
                "id": "rev-1",
                "session_id": SESSION_A_ID,    # session owned by STUDENT_A
                "reviewer_id": TEACHER_ID,
                "rating": 8.0,
                "feedback": "bom",
                "student_reply": None,
                "status": status,
            }],
        )

    def test_owner_reads_own_review(self, client, as_student, fake_supabase):
        self._seed_review(fake_supabase)
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}/review")
        assert_owner_passes(resp)
        assert resp.json()["feedback"] == "bom"

    def test_teacher_reads_any_review(self, client, as_teacher, fake_supabase):
        self._seed_review(fake_supabase)
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}/review")
        assert resp.status_code == 200

    def test_third_student_cannot_read_review(self, client, as_other_student, fake_supabase):
        self._seed_review(fake_supabase)
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}/review")
        assert resp.status_code in (403, 404)
        assert "feedback" not in resp.json()

    def test_owner_replies_and_notifies_reviewer(self, client, as_student, fake_supabase):
        self._seed_review(fake_supabase)
        fake_supabase.seed("notifications", [])
        resp = client.post(f"/chat-sessions/{SESSION_A_ID}/review/reply", json={"reply": "obrigado"})
        assert resp.status_code == 200
        assert fake_supabase.find("session_reviews", id="rev-1")["status"] == "replied"
        assert fake_supabase.find("notifications", user_id=TEACHER_ID) is not None

    def test_cross_actor_cannot_reply_no_mutation(self, client, as_other_student, fake_supabase):
        self._seed_review(fake_supabase)
        fake_supabase.seed("notifications", [])
        fake_supabase.reset_mutations()
        resp = client.post(f"/chat-sessions/{SESSION_A_ID}/review/reply", json={"reply": "hijack"})
        assert resp.status_code in (403, 404)
        assert fake_supabase.find("session_reviews", id="rev-1")["student_reply"] is None
        assert all(m["table"] != "notifications" for m in fake_supabase.mutations)

    def test_create_reviewer_id_from_token_not_body(self, client, as_teacher, fake_supabase):
        # (3) TEACHER creates a review forging reviewer_id/user_id in the body — the
        # stored reviewer_id must be the authenticated TEACHER, never the forged value.
        fake_supabase.seed("session_reviews", [])
        resp = client.post(
            f"/chat-sessions/{SESSION_A_ID}/review",
            json={"rating": 9, "feedback": "ok", "reviewer_id": STUDENT_B_ID, "user_id": STUDENT_B_ID},
        )
        assert resp.status_code == 201
        assert fake_supabase.find("session_reviews", session_id=SESSION_A_ID)["reviewer_id"] == TEACHER_ID

    def test_student_cannot_create_review(self, client, as_student, fake_supabase):
        fake_supabase.seed("session_reviews", [])
        fake_supabase.reset_mutations()
        resp = client.post(f"/chat-sessions/{SESSION_A_ID}/review", json={"rating": 9})
        assert resp.status_code == 403
        assert all(m["table"] != "session_reviews" for m in fake_supabase.mutations)


# ===========================================================================
# Caller 5 (canonical) — chat-sessions create: body.user_id never trusted (bug #2)
# ===========================================================================
class TestChatSessionBodyUserIdIgnored:
    def test_create_session_ignores_forged_body_user_id(self, client, as_student, fake_supabase):
        # (3) The exemplar anti-pattern from create_or_get_chat_session
        # (``uid = data.user_id or current_user["id"]``). A STUDENT forging
        # user_id=STUDENT_B must NOT create/own a session for the victim.
        def _call(payload):
            payload = dict(payload)
            payload.setdefault("content_id", "content-spoof")
            return client.post("/chat-sessions", json=payload)

        def _effective(resp):
            return resp.json().get("user_id")

        assert_body_user_id_ignored(
            call=_call,
            authenticated_user_id=STUDENT_A_ID,
            forged_user_id=STUDENT_B_ID,
            effective_user_id_of=_effective,
        )
        assert fake_supabase.find("chat_sessions", user_id=STUDENT_B_ID, content_id="content-spoof") is None

    def test_admin_create_session_owned_by_admin_not_forged_body(self, client, as_admin):
        resp = client.post("/chat-sessions", json={"content_id": "content-admin", "user_id": STUDENT_B_ID})
        assert resp.status_code in (200, 201)
        assert resp.json()["user_id"] == ADMIN_ID  # owned by the actor, never the body id
