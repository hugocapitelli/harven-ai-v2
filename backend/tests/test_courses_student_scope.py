"""P1 fix 4 — ``GET /courses`` scoped for STUDENT.

The listing applied no enrollment/status filter, so any student saw EVERY course
on the platform — drafts included, other classes included. Now a STUDENT only
sees ``status='active'`` courses of disciplines they are enrolled in
(``discipline_students``); ADMIN/TEACHER keep the unfiltered listing.

Seed context (conftest): STUDENT_A is enrolled in DISCIPLINE_ID only;
OTHER_DISCIPLINE_ID has no enrollment for them.
"""
from __future__ import annotations

from conftest import DISCIPLINE_ID, OTHER_DISCIPLINE_ID


def _seed_courses(fake):
    fake.add("courses", {"id": "c-active-own", "title": "Ativo Meu",
                         "discipline_id": DISCIPLINE_ID, "status": "active",
                         "created_at": "2026-01-01T00:00:00Z"})
    fake.add("courses", {"id": "c-draft-own", "title": "Rascunho Meu",
                         "discipline_id": DISCIPLINE_ID, "status": "draft",
                         "created_at": "2026-01-02T00:00:00Z"})
    fake.add("courses", {"id": "c-active-other", "title": "Ativo Alheio",
                         "discipline_id": OTHER_DISCIPLINE_ID, "status": "active",
                         "created_at": "2026-01-03T00:00:00Z"})


class TestStudentScope:
    def test_student_sees_only_enrolled_active_courses(self, client, as_student, fake_supabase):
        _seed_courses(fake_supabase)
        resp = client.get("/courses")
        assert resp.status_code == 200, resp.text
        ids = {c["id"] for c in resp.json()["data"]}
        assert ids == {"c-active-own"}

    def test_student_filter_by_unenrolled_discipline_is_empty(self, client, as_student, fake_supabase):
        _seed_courses(fake_supabase)
        resp = client.get("/courses", params={"discipline_id": OTHER_DISCIPLINE_ID})
        assert resp.status_code == 200
        assert resp.json()["data"] == []
        assert resp.json()["total"] == 0

    def test_student_filter_by_enrolled_discipline_excludes_drafts(self, client, as_student, fake_supabase):
        _seed_courses(fake_supabase)
        resp = client.get("/courses", params={"discipline_id": DISCIPLINE_ID})
        ids = {c["id"] for c in resp.json()["data"]}
        assert ids == {"c-active-own"}

    def test_student_with_no_enrollment_sees_nothing(self, client, as_other_student, fake_supabase):
        _seed_courses(fake_supabase)
        resp = client.get("/courses")
        assert resp.status_code == 200
        assert resp.json()["data"] == []


class TestStaffKeepsFullListing:
    def test_admin_sees_everything_including_drafts(self, client, as_admin, fake_supabase):
        _seed_courses(fake_supabase)
        resp = client.get("/courses")
        ids = {c["id"] for c in resp.json()["data"]}
        assert {"c-active-own", "c-draft-own", "c-active-other"} <= ids

    def test_teacher_sees_everything(self, client, as_teacher, fake_supabase):
        _seed_courses(fake_supabase)
        resp = client.get("/courses")
        ids = {c["id"] for c in resp.json()["data"]}
        assert {"c-active-own", "c-draft-own", "c-active-other"} <= ids
