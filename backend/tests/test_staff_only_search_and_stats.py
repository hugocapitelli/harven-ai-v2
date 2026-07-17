"""P1 fixes 2+3 — ``GET /search`` and ``GET /dashboard/stats`` are staff-only.

Both were gated by bare ``get_current_user``:
  * ``/search`` returned users (name/email/RA), draft courses and every
    discipline to ANY authenticated student — a base-wide enumeration primitive;
  * ``/dashboard/stats`` leaked institutional aggregates (user totals, role
    breakdown, average performance) to students.

Both now require ADMIN/TEACHER/INSTRUCTOR.
"""
from __future__ import annotations


class TestSearchIsStaffOnly:
    def test_student_is_403(self, client, as_student):
        resp = client.get("/search", params={"q": "student"})
        assert resp.status_code == 403, resp.text

    def test_teacher_can_search(self, client, as_teacher):
        resp = client.get("/search", params={"q": "student"})
        assert resp.status_code == 200, resp.text
        assert "users" in resp.json()

    def test_admin_can_search(self, client, as_admin):
        resp = client.get("/search", params={"q": "student"})
        assert resp.status_code == 200, resp.text


class TestDashboardStatsIsStaffOnly:
    def test_student_is_403(self, client, as_student):
        resp = client.get("/dashboard/stats")
        assert resp.status_code == 403, resp.text

    def test_teacher_can_read(self, client, as_teacher):
        resp = client.get("/dashboard/stats")
        assert resp.status_code == 200, resp.text

    def test_admin_can_read(self, client, as_admin):
        resp = client.get("/dashboard/stats")
        assert resp.status_code == 200, resp.text
