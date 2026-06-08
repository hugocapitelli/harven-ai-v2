"""Regression IDOR suite for the gamification READ endpoints (SEC-READ-1).

Closes the five residual read-IDORs that QA flagged as
``scope_registry.KNOWN_UNREMEDIATED`` debt — all in ``routes_admin.py``:

* ``GET /users/{user_id}/stats``                       (user_stats)
* ``GET /users/{user_id}/activities``                  (user_activities)
* ``GET /users/{user_id}/achievements``                (user_achievements)
* ``GET /users/{user_id}/certificates``                (user_certificates)
* ``GET /users/{user_id}/courses/{course_id}/progress``(user_course_progress)

Each used to sign ``_user: dict = Depends(get_current_user)`` (JWT proof only) and
read by ``user_id`` from the PATH without ever comparing it to the authenticated
identity — a STUDENT could read any peer's points / achievements / certificates /
stats / course progress. The fix imports ``require_self_or_role`` from
``authz.py`` (never redefined) and runs it BEFORE any read:

    require_self_or_role(user_id, current_user, "ADMIN", "TEACHER")

so a STUDENT may read ONLY their own ``user_id``; ADMIN/TEACHER may read others.

3-outcome contract asserted per endpoint:
  (1) the authenticated **owner** passes (reaches the read / 2xx);
  (2) a **cross-user STUDENT** is rejected (403) with no third-party data in the
      body — the path ``user_id`` never promotes them to "owner";
  (3) a **privileged role** (ADMIN / TEACHER) may read another user's resource.

Harness reuse: the shared ``conftest.py`` fixtures (fake Supabase, seed identities,
``as_*`` actor overrides) and the seed's gamification tables. ``conftest.py`` is
NOT edited.

Fake-operator note (mirrors ``test_idor_admin.py``): the in-memory fake implements
``.eq``/``.order``/``.maybe_single``/``.select(count=...)`` but NOT ``.range()``.
The authorization gate in every endpoint runs BEFORE any query, so all deny paths
hit the gate directly (clean 403, no read). For the owner/privileged happy paths:
* ``user_stats`` / ``user_course_progress`` use ``.maybe_single()`` -> a clean 200
  (default body) even with no seeded row;
* ``user_achievements`` / ``user_certificates`` use ``.order().execute()`` -> a
  clean 200 (empty/seeded list);
* ``user_activities`` uses ``.range()`` (unimplemented in the fake), so we prove the
  gate let the actor THROUGH to the query layer by asserting the response is NOT a
  403 (reaching the unimplemented pagination, exactly like
  ``TestNotificationsIDOR.test_list_owner_passes_the_gate``).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import (
    STUDENT_A_ID,
    STUDENT_B_ID,
)
from idor_helpers import assert_owner_passes


def _passes_gate(app, method: str, url: str) -> "object":
    """Issue a request that may reach an unimplemented fake operator (``.range()``).

    Returns the response from a permissive TestClient (server exceptions become
    500 instead of propagating), so the caller can assert the gate let the actor
    through (status != 403) rather than depending on the fake implementing every
    downstream chain.
    """
    permissive = TestClient(app, raise_server_exceptions=False)
    return permissive.request(method, url)


# ===========================================================================
# GET /users/{user_id}/stats
# ===========================================================================
class TestUserStatsReadIDOR:
    def test_owner_passes(self, client, as_student):
        resp = client.get(f"/users/{STUDENT_A_ID}/stats")
        assert_owner_passes(resp)
        assert resp.json()["user_id"] == STUDENT_A_ID

    def test_cross_actor_forbidden_no_leak(self, client, as_other_student):
        # STUDENT_B reading STUDENT_A's stats — denied before any read.
        resp = client.get(f"/users/{STUDENT_A_ID}/stats")
        assert resp.status_code == 403
        assert "total_points" not in resp.json()

    def test_admin_reads_other_user(self, client, as_admin):
        resp = client.get(f"/users/{STUDENT_A_ID}/stats")
        assert resp.status_code == 200
        assert resp.json()["user_id"] == STUDENT_A_ID

    def test_teacher_reads_other_user(self, client, as_teacher):
        resp = client.get(f"/users/{STUDENT_A_ID}/stats")
        assert resp.status_code == 200


# ===========================================================================
# GET /users/{user_id}/activities  (uses .range() -> prove gate via "not 403")
# ===========================================================================
class TestUserActivitiesReadIDOR:
    def test_owner_passes_the_gate(self, app, as_student):
        resp = _passes_gate(app, "GET", f"/users/{STUDENT_A_ID}/activities")
        # 500 here == reached the (unimplemented) .range() pagination, i.e. the
        # gate allowed the owner through; a 403 would mean the gate blocked them.
        assert resp.status_code != 403

    def test_cross_actor_forbidden_no_leak(self, client, as_other_student):
        resp = client.get(f"/users/{STUDENT_A_ID}/activities")
        assert resp.status_code == 403
        assert "data" not in resp.json()

    def test_admin_passes_the_gate(self, app, as_admin):
        resp = _passes_gate(app, "GET", f"/users/{STUDENT_A_ID}/activities")
        assert resp.status_code != 403

    def test_teacher_passes_the_gate(self, app, as_teacher):
        resp = _passes_gate(app, "GET", f"/users/{STUDENT_A_ID}/activities")
        assert resp.status_code != 403


# ===========================================================================
# GET /users/{user_id}/achievements
# ===========================================================================
class TestUserAchievementsReadIDOR:
    def test_owner_passes(self, client, as_student, fake_supabase):
        fake_supabase.seed("user_achievements", [])  # owner with no achievements -> 200, empty
        resp = client.get(f"/users/{STUDENT_A_ID}/achievements")
        assert_owner_passes(resp)
        assert resp.json()["data"] == []

    def test_cross_actor_forbidden_no_leak(self, client, as_other_student, fake_supabase):
        fake_supabase.seed(
            "user_achievements",
            [{"id": "ach-a", "user_id": STUDENT_A_ID, "name": "secret"}],
        )
        resp = client.get(f"/users/{STUDENT_A_ID}/achievements")
        assert resp.status_code == 403
        assert "data" not in resp.json()

    def test_admin_reads_other_user(self, client, as_admin, fake_supabase):
        fake_supabase.seed("user_achievements", [])
        resp = client.get(f"/users/{STUDENT_A_ID}/achievements")
        assert resp.status_code == 200

    def test_teacher_reads_other_user(self, client, as_teacher, fake_supabase):
        fake_supabase.seed("user_achievements", [])
        resp = client.get(f"/users/{STUDENT_A_ID}/achievements")
        assert resp.status_code == 200


# ===========================================================================
# GET /users/{user_id}/certificates
# ===========================================================================
class TestUserCertificatesReadIDOR:
    def test_owner_passes(self, client, as_student, fake_supabase):
        fake_supabase.seed("certificates", [])
        resp = client.get(f"/users/{STUDENT_A_ID}/certificates")
        assert_owner_passes(resp)
        assert resp.json()["data"] == []

    def test_cross_actor_forbidden_no_leak(self, client, as_other_student, fake_supabase):
        fake_supabase.seed(
            "certificates",
            [{"id": "cert-a", "user_id": STUDENT_A_ID, "certificate_number": "HARVEN-SECRET"}],
        )
        resp = client.get(f"/users/{STUDENT_A_ID}/certificates")
        assert resp.status_code == 403
        assert "data" not in resp.json()

    def test_admin_reads_other_user(self, client, as_admin, fake_supabase):
        fake_supabase.seed("certificates", [])
        resp = client.get(f"/users/{STUDENT_A_ID}/certificates")
        assert resp.status_code == 200

    def test_teacher_reads_other_user(self, client, as_teacher, fake_supabase):
        fake_supabase.seed("certificates", [])
        resp = client.get(f"/users/{STUDENT_A_ID}/certificates")
        assert resp.status_code == 200


# ===========================================================================
# GET /users/{user_id}/courses/{course_id}/progress
# ===========================================================================
class TestUserCourseProgressReadIDOR:
    def test_owner_passes(self, client, as_student):
        resp = client.get(f"/users/{STUDENT_A_ID}/courses/course-1/progress")
        assert_owner_passes(resp)
        assert resp.json()["user_id"] == STUDENT_A_ID

    def test_cross_actor_forbidden_no_leak(self, client, as_other_student, fake_supabase):
        # Seed STUDENT_A's real progress so a leak (if any) would be visible.
        fake_supabase.seed(
            "course_progress",
            [{"id": "cp-a", "user_id": STUDENT_A_ID, "course_id": "course-1",
              "progress_percent": 87.0, "completed_contents": 5, "total_contents": 6}],
        )
        resp = client.get(f"/users/{STUDENT_A_ID}/courses/course-1/progress")
        assert resp.status_code == 403
        assert "progress_percent" not in resp.json()

    def test_admin_reads_other_user(self, client, as_admin):
        resp = client.get(f"/users/{STUDENT_A_ID}/courses/course-1/progress")
        assert resp.status_code == 200
        assert resp.json()["user_id"] == STUDENT_A_ID

    def test_teacher_reads_other_user(self, client, as_teacher):
        resp = client.get(f"/users/{STUDENT_A_ID}/courses/course-1/progress")
        assert resp.status_code == 200
