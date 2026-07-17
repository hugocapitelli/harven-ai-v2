"""P1 fix 5 — broadcast audience labels mapped to REAL DB roles.

The UI sends 'STUDENTS'/'INSTRUCTORS' but the users table stores
STUDENT/TEACHER/ADMIN. The old ``eq("role", target.upper())`` compared plural
labels against singular roles (and INSTRUCTOR against the stored TEACHER), so
audience broadcasts matched ZERO users and reported ``{"sent": 0}`` as if that
were success. Seed: 2 STUDENTs, 1 TEACHER, 1 ADMIN (conftest).
"""
from __future__ import annotations


def _sent_titles_by_user(fake):
    out: dict[str, list[str]] = {}
    for n in fake.rows("notifications"):
        out.setdefault(n["user_id"], []).append(n.get("title"))
    return out


class TestBroadcastTargets:
    def _post(self, client, target):
        return client.post(
            "/notifications/broadcast",
            json={"title": f"Aviso {target}", "message": "corpo", "target": target},
        )

    def test_students_label_reaches_students(self, client, as_admin, fake_supabase):
        resp = self._post(client, "STUDENTS")
        assert resp.status_code == 200, resp.text
        assert resp.json()["sent"] == 2  # student-a + student-b

    def test_instructors_label_reaches_teacher_rows(self, client, as_admin, fake_supabase):
        """INSTRUCTORS (UI label) must reach users stored with role=TEACHER."""
        resp = self._post(client, "INSTRUCTORS")
        assert resp.status_code == 200, resp.text
        assert resp.json()["sent"] == 1  # teacher-1 (stored as TEACHER)
        titles = _sent_titles_by_user(fake_supabase)
        assert "Aviso INSTRUCTORS" in (titles.get("teacher-1") or [])

    def test_all_reaches_everyone(self, client, as_admin, fake_supabase):
        resp = self._post(client, "all")
        assert resp.json()["sent"] == 4

    def test_admins_label(self, client, as_admin):
        resp = self._post(client, "ADMINS")
        assert resp.json()["sent"] == 1

    def test_unknown_target_is_400_not_silent_zero(self, client, as_admin):
        resp = self._post(client, "EVERYBODY")
        assert resp.status_code == 400, resp.text
