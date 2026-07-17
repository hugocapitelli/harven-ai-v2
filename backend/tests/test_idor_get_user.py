"""P1 fix 1 — IDOR on ``GET /users/{user_id}``.

The route required only ``get_current_user``, so any authenticated STUDENT could
enumerate ids and read any user's profile (name, email, RA). Now only the target
user themselves or a privileged role (ADMIN/TEACHER/INSTRUCTOR) may read it.
"""
from __future__ import annotations

from conftest import STUDENT_A_ID, STUDENT_B_ID, TEACHER_ID


class TestGetUserIdor:
    def test_student_reads_own_profile(self, client, as_student):
        resp = client.get(f"/users/{STUDENT_A_ID}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == STUDENT_A_ID

    def test_student_cannot_read_other_student(self, client, as_student):
        resp = client.get(f"/users/{STUDENT_B_ID}")
        assert resp.status_code == 403, resp.text

    def test_student_cannot_read_teacher(self, client, as_student):
        resp = client.get(f"/users/{TEACHER_ID}")
        assert resp.status_code == 403, resp.text

    def test_teacher_reads_student(self, client, as_teacher):
        resp = client.get(f"/users/{STUDENT_A_ID}")
        assert resp.status_code == 200, resp.text

    def test_admin_reads_anyone(self, client, as_admin):
        resp = client.get(f"/users/{STUDENT_B_ID}")
        assert resp.status_code == 200, resp.text
