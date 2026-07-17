"""P1 fix 6 — ``POST /classes/{id}/courses`` must respect the requested status.

The route overwrote whatever the teacher sent with ``status='active'``, silently
publishing to students a course explicitly created as draft. Now the requested
status is honored and the default (omitted) is 'draft' — the same contract as
``POST /courses``.
"""
from __future__ import annotations

from conftest import DISCIPLINE_ID


class TestClassCourseStatus:
    def test_draft_stays_draft(self, client, as_teacher, fake_supabase):
        resp = client.post(
            f"/classes/{DISCIPLINE_ID}/courses",
            json={"title": "Curso Rascunho", "status": "draft"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "draft"
        row = fake_supabase.find("courses", title="Curso Rascunho")
        assert row["status"] == "draft"

    def test_explicit_active_is_respected(self, client, as_teacher, fake_supabase):
        resp = client.post(
            f"/classes/{DISCIPLINE_ID}/courses",
            json={"title": "Curso Publicado", "status": "active"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "active"

    def test_omitted_status_defaults_to_draft(self, client, as_teacher, fake_supabase):
        resp = client.post(
            f"/classes/{DISCIPLINE_ID}/courses",
            json={"title": "Curso Sem Status"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "draft"
