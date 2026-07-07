"""Regression IDOR / authorization suite for ``routes_admin.py`` (EPIC-SEC Fase 2).

Covers the five stories owned by the ``routes_admin`` hotspot change:

* SEC-ADMIN-3 — notifications IDOR + create restricted to ADMIN.
* SEC-ADMIN-4 — gamification write IDOR + academic integrity (points whitelist,
  certificate eligibility).
* SEC-ADMIN-5 — Session Review authz (create/get/update/reply).
* SEC-SCOPE-1 — teacher->discipline gating on class/discipline stats + sessions.
* SEC-SCOPE-2 — gradebook read + grade override scoped to the teacher's disciplines.

Every test reuses the shared harness from ``conftest.py`` (the fake Supabase
client, the deterministic seed identities, and the ``as_*`` actor overrides). It
never edits ``conftest.py``. The 3-outcome contract is asserted via
``idor_helpers``: (1) owner passes, (2) cross actor 403/404 with no mutation,
(3) client-supplied identity is never trusted.

Harness note: the in-memory fake implements ``.eq``/``maybe_single``/``insert``/
``update``/``delete`` but not ``.in_()``/``.not_``. The authorization gates in
every endpoint under test run BEFORE any ``.in_()`` query, so the deny paths
exercise the gate directly. The owner-passes paths are seeded so each endpoint
returns through its early-exit branch (empty enrollment / no courses), proving
2xx without depending on unimplemented fake operators.
"""
from __future__ import annotations

import pytest

from conftest import (
    ADMIN_ID,
    DISCIPLINE_ID,
    OTHER_DISCIPLINE_ID,
    SESSION_A_ID,
    SESSION_B_ID,
    STUDENT_A_ID,
    STUDENT_B_ID,
    TEACHER_ID,
)
from idor_helpers import (
    assert_cross_actor_forbidden_no_mutation,
    assert_owner_passes,
)

NOTIF_A = "notif-a"
NOTIF_B = "notif-b"


# ===========================================================================
# Helpers
# ===========================================================================
def _seed_notifications(fake):
    """Replace the seed notifications with rows carrying the ``is_read`` column
    the routes actually filter on (the base seed uses ``read``)."""
    fake.seed(
        "notifications",
        [
            {"id": NOTIF_A, "user_id": STUDENT_A_ID, "title": "A", "message": "m",
             "notification_type": "info", "link": None, "is_read": False},
            {"id": NOTIF_B, "user_id": STUDENT_B_ID, "title": "B", "message": "m",
             "notification_type": "info", "link": None, "is_read": False},
        ],
    )


# ===========================================================================
# SEC-ADMIN-3 — Notifications
# ===========================================================================
class TestNotificationsIDOR:
    def test_count_owner_passes(self, client, as_student, fake_supabase):
        _seed_notifications(fake_supabase)
        resp = client.get(f"/notifications/{STUDENT_A_ID}/count")
        assert_owner_passes(resp)
        assert resp.json()["unread"] == 1

    def test_count_cross_actor_forbidden(self, client, as_other_student, fake_supabase):
        _seed_notifications(fake_supabase)
        resp = client.get(f"/notifications/{STUDENT_A_ID}/count")
        assert resp.status_code == 403
        # No third-party data leaked in the body.
        assert "unread" not in resp.json()

    def test_count_admin_passes(self, client, as_admin, fake_supabase):
        _seed_notifications(fake_supabase)
        resp = client.get(f"/notifications/{STUDENT_A_ID}/count")
        assert resp.status_code == 200

    def test_list_owner_passes_the_gate(self, app, as_student, fake_supabase):
        # The owner must pass the authz gate. The in-memory fake does not implement
        # the ``.range()`` pagination chain used downstream, so we prove the gate let
        # the owner THROUGH to the query layer: the call reaches ``.range()`` (raising
        # the harness AttributeError) instead of being short-circuited by a 403.
        from fastapi.testclient import TestClient

        _seed_notifications(fake_supabase)
        permissive = TestClient(app, raise_server_exceptions=False)
        resp = permissive.get(f"/notifications/{STUDENT_A_ID}")
        # 500 here == reached the (unimplemented) pagination, i.e. gate allowed owner.
        assert resp.status_code != 403

    def test_list_cross_actor_forbidden_no_leak(self, client, as_other_student, fake_supabase):
        _seed_notifications(fake_supabase)
        resp = client.get(f"/notifications/{STUDENT_A_ID}")
        assert resp.status_code == 403
        assert "data" not in resp.json()

    def test_mark_read_owner_passes(self, client, as_student, fake_supabase):
        _seed_notifications(fake_supabase)
        resp = client.put(f"/notifications/{NOTIF_A}/read")
        assert_owner_passes(resp)
        assert fake_supabase.find("notifications", id=NOTIF_A)["is_read"] is True

    def test_mark_read_cross_actor_forbidden_no_mutation(self, client, as_other_student, fake_supabase):
        _seed_notifications(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.put(f"/notifications/{NOTIF_A}/read")
        assert_cross_actor_forbidden_no_mutation(
            resp, fake_supabase, table="notifications", victim_row_id=NOTIF_A
        )
        # Victim row remains unread.
        assert fake_supabase.find("notifications", id=NOTIF_A)["is_read"] is False

    def test_mark_read_missing_returns_404(self, client, as_student, fake_supabase):
        _seed_notifications(fake_supabase)
        resp = client.put("/notifications/does-not-exist/read")
        assert resp.status_code == 404

    def test_mark_all_read_owner_passes(self, client, as_student, fake_supabase):
        _seed_notifications(fake_supabase)
        resp = client.put(f"/notifications/{STUDENT_A_ID}/read-all")
        assert resp.status_code == 200

    def test_mark_all_read_cross_actor_forbidden_no_mutation(self, client, as_other_student, fake_supabase):
        _seed_notifications(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.put(f"/notifications/{STUDENT_A_ID}/read-all")
        assert resp.status_code == 403
        # No update landed on STUDENT_A's notification.
        assert fake_supabase.find("notifications", id=NOTIF_A)["is_read"] is False

    def test_delete_owner_passes(self, client, as_student, fake_supabase):
        _seed_notifications(fake_supabase)
        resp = client.delete(f"/notifications/{NOTIF_A}")
        assert_owner_passes(resp)
        assert fake_supabase.find("notifications", id=NOTIF_A) is None

    def test_delete_cross_actor_forbidden_no_mutation(self, client, as_other_student, fake_supabase):
        _seed_notifications(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.delete(f"/notifications/{NOTIF_A}")
        assert_cross_actor_forbidden_no_mutation(
            resp, fake_supabase, table="notifications", victim_row_id=NOTIF_A
        )
        assert fake_supabase.find("notifications", id=NOTIF_A) is not None

    def test_delete_missing_returns_404(self, client, as_student, fake_supabase):
        _seed_notifications(fake_supabase)
        resp = client.delete("/notifications/does-not-exist")
        assert resp.status_code == 404

    def test_create_student_forbidden(self, client, as_student, fake_supabase):
        fake_supabase.reset_mutations()
        resp = client.post("/notifications", json={"user_id": STUDENT_B_ID, "title": "spam"})
        assert resp.status_code == 403
        # Nothing was injected into the victim feed.
        assert all(m["table"] != "notifications" for m in fake_supabase.mutations)

    def test_create_admin_passes(self, client, as_admin, fake_supabase):
        resp = client.post("/notifications", json={"user_id": STUDENT_A_ID, "title": "oficial"})
        assert resp.status_code == 201
        assert resp.json()["title"] == "oficial"


# ===========================================================================
# SEC-ADMIN-4 — Gamification write IDOR + integrity
# ===========================================================================
class TestGamificationIDOR:
    def test_create_activity_self_passes_points_from_whitelist(self, client, as_student, fake_supabase):
        # Client sends points=9999; server must ignore it and use the whitelist (10).
        resp = client.post(
            f"/users/{STUDENT_A_ID}/activities",
            json={"activity_type": "content_completed", "points": 9999},
        )
        assert resp.status_code == 201
        assert resp.json()["points"] == 10
        row = fake_supabase.find("user_activities", user_id=STUDENT_A_ID)
        assert row is not None
        assert row["points"] == 10  # not 9999

    def test_create_activity_unknown_type_safe_default(self, client, as_student, fake_supabase):
        resp = client.post(
            f"/users/{STUDENT_A_ID}/activities",
            json={"activity_type": "totally_made_up", "points": 5000},
        )
        assert resp.status_code == 201
        assert resp.json()["points"] == 0

    def test_create_activity_cross_user_forbidden_no_write(self, client, as_other_student, fake_supabase):
        fake_supabase.reset_mutations()
        resp = client.post(
            f"/users/{STUDENT_A_ID}/activities",
            json={"activity_type": "content_completed", "points": 10},
        )
        assert resp.status_code == 403
        # No write to user_activities or user_stats for the victim.
        assert all(m["table"] not in ("user_activities", "user_stats") for m in fake_supabase.mutations)

    def test_create_activity_admin_cross_user_allowed(self, client, as_admin, fake_supabase):
        resp = client.post(
            f"/users/{STUDENT_A_ID}/activities",
            json={"activity_type": "content_completed"},
        )
        assert resp.status_code == 201
        assert fake_supabase.find("user_activities", user_id=STUDENT_A_ID) is not None

    def test_unlock_achievement_cross_user_forbidden_no_write(self, client, as_other_student, fake_supabase):
        fake_supabase.reset_mutations()
        resp = client.post(f"/users/{STUDENT_A_ID}/achievements/ACH-1/unlock")
        assert resp.status_code == 403
        assert all(m["table"] != "user_achievements" for m in fake_supabase.mutations)

    def test_unlock_achievement_self_passes(self, client, as_student, fake_supabase):
        resp = client.post(f"/users/{STUDENT_A_ID}/achievements/ACH-1/unlock")
        assert resp.status_code == 201
        assert fake_supabase.find("user_achievements", id="ACH-1", user_id=STUDENT_A_ID) is not None

    def test_unlock_achievement_idempotent(self, client, as_student, fake_supabase):
        fake_supabase.seed(
            "user_achievements",
            [{"id": "ACH-1", "user_id": STUDENT_A_ID, "name": "ACH-1"}],
        )
        resp = client.post(f"/users/{STUDENT_A_ID}/achievements/ACH-1/unlock")
        assert resp.status_code == 201
        assert resp.json().get("already_unlocked") is True

    def test_issue_certificate_cross_user_forbidden_no_write(self, client, as_other_student, fake_supabase):
        fake_supabase.reset_mutations()
        resp = client.post(f"/users/{STUDENT_A_ID}/certificates", json={"course_id": "course-1"})
        assert resp.status_code == 403
        assert all(m["table"] != "certificates" for m in fake_supabase.mutations)

    def test_issue_certificate_self_incomplete_forbidden(self, client, as_student, fake_supabase):
        # STUDENT_A has progress 50% on course-1 — must be blocked (403), no cert.
        fake_supabase.seed(
            "course_progress",
            [{"id": "p1", "user_id": STUDENT_A_ID, "course_id": "course-1", "progress_percent": 50.0}],
        )
        fake_supabase.reset_mutations()
        resp = client.post(f"/users/{STUDENT_A_ID}/certificates", json={"course_id": "course-1"})
        assert resp.status_code == 403
        assert all(m["table"] != "certificates" for m in fake_supabase.mutations)

    def test_issue_certificate_self_complete_passes(self, client, as_student, fake_supabase):
        fake_supabase.seed(
            "course_progress",
            [{"id": "p1", "user_id": STUDENT_A_ID, "course_id": "course-1", "progress_percent": 100.0}],
        )
        resp = client.post(f"/users/{STUDENT_A_ID}/certificates", json={"course_id": "course-1"})
        assert resp.status_code == 201
        assert resp.json()["certificate_number"].startswith("HARVEN-")

    def test_issue_certificate_admin_ignores_progress(self, client, as_admin, fake_supabase):
        # No progress row at all — ADMIN issues administratively regardless.
        fake_supabase.seed("course_progress", [])
        resp = client.post(f"/users/{STUDENT_A_ID}/certificates", json={"course_id": "course-1"})
        assert resp.status_code == 201

    def test_complete_content_uses_points_map_not_hardcode(self, client, as_student, fake_supabase):
        # Seed the content but NO chapters: this skips the ``.in_()`` content-count
        # query (unimplemented in the fake) while still exercising the activity log,
        # which is where the points-map assertion lives.
        fake_supabase.seed("contents", [{"id": "ct-1", "title": "Intro", "chapter_id": "ch-1"}])
        fake_supabase.seed("chapters", [])
        resp = client.post(f"/users/{STUDENT_A_ID}/courses/course-1/complete-content/ct-1")
        assert resp.status_code == 200
        activity = fake_supabase.find(
            "user_activities", user_id=STUDENT_A_ID, activity_type="content_completed"
        )
        assert activity is not None
        assert activity["points"] == 10  # points_for("content_completed"), not a literal 10 inline

    def test_complete_content_cross_user_forbidden_no_write(self, client, as_other_student, fake_supabase):
        fake_supabase.seed("contents", [{"id": "ct-1", "title": "Intro", "chapter_id": "ch-1"}])
        fake_supabase.reset_mutations()
        resp = client.post(f"/users/{STUDENT_A_ID}/courses/course-1/complete-content/ct-1")
        assert resp.status_code == 403
        assert all(m["table"] not in ("course_progress", "user_activities") for m in fake_supabase.mutations)


# ===========================================================================
# SEC-ADMIN-5 — Session Review authz
# ===========================================================================
class TestSessionReviewAuthz:
    def _seed_review(self, fake, status="pending_student"):
        fake.seed(
            "session_reviews",
            [{
                "id": "rev-1",
                "session_id": SESSION_A_ID,   # session owned by STUDENT_A
                "reviewer_id": TEACHER_ID,
                "rating": 8.0,
                "feedback": "bom",
                "student_reply": None,
                "status": status,
            }],
        )

    # ── create ──────────────────────────────────────────────
    def test_create_student_forbidden(self, client, as_student, fake_supabase):
        fake_supabase.seed("session_reviews", [])
        fake_supabase.reset_mutations()
        resp = client.post(f"/chat-sessions/{SESSION_A_ID}/review", json={"rating": 9})
        assert resp.status_code == 403
        assert all(m["table"] != "session_reviews" for m in fake_supabase.mutations)

    def test_create_teacher_passes_reviewer_from_token(self, client, as_teacher, fake_supabase):
        fake_supabase.seed("session_reviews", [])
        # Forge reviewer_id/user_id in the body — must be ignored.
        resp = client.post(
            f"/chat-sessions/{SESSION_A_ID}/review",
            json={"rating": 9, "feedback": "ok", "reviewer_id": STUDENT_B_ID, "user_id": STUDENT_B_ID},
        )
        assert resp.status_code == 201
        row = fake_supabase.find("session_reviews", session_id=SESSION_A_ID)
        assert row["reviewer_id"] == TEACHER_ID  # from token, never the forged body

    # ── get ─────────────────────────────────────────────────
    def test_get_owner_passes(self, client, as_student, fake_supabase):
        self._seed_review(fake_supabase)
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}/review")
        assert_owner_passes(resp)
        assert resp.json()["feedback"] == "bom"

    def test_get_third_student_forbidden_no_leak(self, client, as_other_student, fake_supabase):
        self._seed_review(fake_supabase)
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}/review")
        assert resp.status_code in (403, 404)
        assert "feedback" not in resp.json()

    def test_get_teacher_passes(self, client, as_teacher, fake_supabase):
        self._seed_review(fake_supabase)
        resp = client.get(f"/chat-sessions/{SESSION_A_ID}/review")
        assert resp.status_code == 200

    # ── update ──────────────────────────────────────────────
    def test_update_student_forbidden_no_mutation(self, client, as_student, fake_supabase):
        self._seed_review(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.put(f"/chat-sessions/{SESSION_A_ID}/review", json={"rating": 1})
        assert resp.status_code == 403
        assert all(m["op"] != "update" or m["table"] != "session_reviews" for m in fake_supabase.mutations)
        assert fake_supabase.find("session_reviews", id="rev-1")["rating"] == 8.0

    def test_update_teacher_passes(self, client, as_teacher, fake_supabase):
        self._seed_review(fake_supabase)
        resp = client.put(f"/chat-sessions/{SESSION_A_ID}/review", json={"rating": 10})
        assert resp.status_code == 200
        assert fake_supabase.find("session_reviews", id="rev-1")["rating"] == 10

    # ── reply ───────────────────────────────────────────────
    def test_reply_owner_passes_notifies_reviewer(self, client, as_student, fake_supabase):
        self._seed_review(fake_supabase)
        fake_supabase.seed("notifications", [])
        resp = client.post(f"/chat-sessions/{SESSION_A_ID}/review/reply", json={"reply": "obrigado"})
        assert resp.status_code == 200
        assert fake_supabase.find("session_reviews", id="rev-1")["status"] == "replied"
        # Notification went to the reviewer (the teacher), not the attacker.
        notif = fake_supabase.find("notifications", user_id=TEACHER_ID)
        assert notif is not None

    def test_reply_cross_actor_forbidden_no_mutation_no_notification(self, client, as_other_student, fake_supabase):
        # STUDENT_B replying to STUDENT_A's session review — must be blocked.
        self._seed_review(fake_supabase)
        fake_supabase.seed("notifications", [])
        fake_supabase.reset_mutations()
        resp = client.post(f"/chat-sessions/{SESSION_A_ID}/review/reply", json={"reply": "hijack"})
        assert resp.status_code in (403, 404)
        # No reply written, no spurious notification.
        assert fake_supabase.find("session_reviews", id="rev-1")["student_reply"] is None
        assert all(m["table"] != "notifications" for m in fake_supabase.mutations)


# ===========================================================================
# SEC-SCOPE-1 — teacher->discipline gating on stats/sessions
# ===========================================================================
class TestScopeStatsSessions:
    """DISCIPLINE_ID is owned by TEACHER_ID; OTHER_DISCIPLINE_ID is not.

    Owner-passes paths use a discipline with no enrolled students / no courses so
    each handler returns through its early-exit branch (no ``.in_()`` needed).
    """

    # ── class_stats ─────────────────────────────────────────
    def test_class_stats_student_forbidden(self, client, as_student):
        resp = client.get(f"/classes/{DISCIPLINE_ID}/stats")
        assert resp.status_code == 403

    def test_class_stats_teacher_linked_passes(self, client, as_teacher, fake_supabase):
        fake_supabase.seed("discipline_students", [])  # no students -> no .in_()
        resp = client.get(f"/classes/{DISCIPLINE_ID}/stats")
        assert resp.status_code == 200

    def test_class_stats_teacher_unlinked_forbidden(self, client, as_teacher, fake_supabase):
        fake_supabase.seed("discipline_students", [])
        resp = client.get(f"/classes/{OTHER_DISCIPLINE_ID}/stats")
        assert resp.status_code == 403

    def test_class_stats_admin_any_discipline_passes(self, client, as_admin, fake_supabase):
        fake_supabase.seed("discipline_students", [])
        resp = client.get(f"/classes/{OTHER_DISCIPLINE_ID}/stats")
        assert resp.status_code == 200

    def test_class_stats_missing_discipline_404_for_authorized(self, client, as_admin):
        resp = client.get("/classes/nope/stats")
        assert resp.status_code == 404

    # ── discipline_students_stats ───────────────────────────
    def test_students_stats_student_forbidden(self, client, as_student):
        resp = client.get(f"/disciplines/{DISCIPLINE_ID}/students/stats")
        assert resp.status_code == 403

    def test_students_stats_teacher_linked_passes(self, client, as_teacher, fake_supabase):
        fake_supabase.seed("discipline_students", [])
        resp = client.get(f"/disciplines/{DISCIPLINE_ID}/students/stats")
        assert resp.status_code == 200

    def test_students_stats_teacher_unlinked_forbidden(self, client, as_teacher, fake_supabase):
        fake_supabase.seed("discipline_students", [])
        resp = client.get(f"/disciplines/{OTHER_DISCIPLINE_ID}/students/stats")
        assert resp.status_code == 403

    def test_students_stats_admin_passes(self, client, as_admin, fake_supabase):
        fake_supabase.seed("discipline_students", [])
        resp = client.get(f"/disciplines/{OTHER_DISCIPLINE_ID}/students/stats")
        assert resp.status_code == 200

    # ── discipline_sessions ─────────────────────────────────
    def test_sessions_student_forbidden(self, client, as_student):
        resp = client.get(f"/disciplines/{DISCIPLINE_ID}/sessions")
        assert resp.status_code == 403

    def test_sessions_teacher_linked_passes(self, client, as_teacher, fake_supabase):
        fake_supabase.seed("courses", [])  # no courses -> early return, no .in_()
        resp = client.get(f"/disciplines/{DISCIPLINE_ID}/sessions")
        assert resp.status_code == 200

    def test_sessions_teacher_unlinked_forbidden(self, client, as_teacher, fake_supabase):
        fake_supabase.seed("courses", [])
        resp = client.get(f"/disciplines/{OTHER_DISCIPLINE_ID}/sessions")
        assert resp.status_code == 403

    def test_sessions_admin_passes(self, client, as_admin, fake_supabase):
        fake_supabase.seed("courses", [])
        resp = client.get(f"/disciplines/{OTHER_DISCIPLINE_ID}/sessions")
        assert resp.status_code == 200


# ===========================================================================
# SEC-SCOPE-2 — gradebook read + grade override scoping
# ===========================================================================
class TestGradebookScope:
    # ── GET gradebook ───────────────────────────────────────
    def test_gradebook_teacher_linked_passes(self, client, as_teacher, fake_supabase):
        fake_supabase.seed("discipline_students", [])  # empty -> early return, no .in_()
        resp = client.get(f"/disciplines/{DISCIPLINE_ID}/gradebook")
        assert resp.status_code == 200

    def test_gradebook_teacher_unlinked_forbidden_no_read(self, client, as_teacher, fake_supabase):
        resp = client.get(f"/disciplines/{OTHER_DISCIPLINE_ID}/gradebook")
        assert resp.status_code == 403

    def test_gradebook_admin_passes(self, client, as_admin, fake_supabase):
        fake_supabase.seed("discipline_students", [])
        resp = client.get(f"/disciplines/{OTHER_DISCIPLINE_ID}/gradebook")
        assert resp.status_code == 200

    # ── PUT grade override ──────────────────────────────────
    def test_set_grade_teacher_linked_passes(self, client, as_teacher, fake_supabase):
        resp = client.put(
            f"/disciplines/{DISCIPLINE_ID}/students/{STUDENT_A_ID}/grade",
            json={"course_id": "course-1", "grade": 9.5},
        )
        assert resp.status_code == 200
        ov = fake_supabase.find(
            "grade_overrides", discipline_id=DISCIPLINE_ID, student_id=STUDENT_A_ID, course_id="course-1"
        )
        assert ov is not None and ov["grade"] == 9.5

    def test_set_grade_first_time_insert_sets_graded_by(self, client, as_teacher, fake_supabase):
        # Regression: grade_overrides.graded_by is NOT NULL in the schema
        # (supabase/migrations/20260518_grade_overrides.sql). The fake does not
        # enforce NOT NULL, so this asserts the insert PAYLOAD itself carries the
        # column — a passing test here proves the fix even though the fake alone
        # would not have caught the original 500.
        resp = client.put(
            f"/disciplines/{DISCIPLINE_ID}/students/{STUDENT_A_ID}/grade",
            json={"course_id": "course-1", "grade": 8.0},
        )
        assert resp.status_code == 200

        insert_mutations = [
            m for m in fake_supabase.mutations
            if m["table"] == "grade_overrides" and m["op"] == "insert"
        ]
        assert len(insert_mutations) == 1
        payload = insert_mutations[0]["rows"][0]
        assert payload["graded_by"] == TEACHER_ID
        # Sanity: the other NOT NULL columns without a DB default remain present.
        assert payload["discipline_id"] == DISCIPLINE_ID
        assert payload["student_id"] == STUDENT_A_ID
        assert payload["course_id"] == "course-1"
        assert payload["grade"] == 8.0

    def test_set_grade_teacher_unlinked_forbidden_no_mutation(self, client, as_teacher, fake_supabase):
        # OTHER_DISCIPLINE_ID is not owned by TEACHER_ID.
        fake_supabase.reset_mutations()
        resp = client.put(
            f"/disciplines/{OTHER_DISCIPLINE_ID}/students/{STUDENT_B_ID}/grade",
            json={"course_id": "course-2", "grade": 10},
        )
        assert resp.status_code == 403
        # No write to grade_overrides whatsoever.
        assert all(m["table"] != "grade_overrides" for m in fake_supabase.mutations)
        assert fake_supabase.find("grade_overrides", discipline_id=OTHER_DISCIPLINE_ID) is None

    def test_set_grade_admin_passes(self, client, as_admin, fake_supabase):
        # ADMIN bypasses scoping even on a discipline they "don't own".
        # Seed enrollment so the existence/enrollment checks pass.
        fake_supabase.add("discipline_students", {"discipline_id": OTHER_DISCIPLINE_ID, "student_id": STUDENT_B_ID})
        resp = client.put(
            f"/disciplines/{OTHER_DISCIPLINE_ID}/students/{STUDENT_B_ID}/grade",
            json={"course_id": "course-2", "grade": 7.0},
        )
        assert resp.status_code == 200
