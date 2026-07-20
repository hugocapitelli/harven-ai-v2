"""SEC-SCOPE-8 — cross-teacher IDOR regression suite for the course/chapter/
content/question CRUD in ``main.py``.

Context
=======
EPIC-SEC Fase 2 blindou apenas as rotas discipline-scoped de ``routes_admin.py``.
O CRUD principal de curso/capítulo/conteúdo/questão vive em ``main.py`` e ficou
descoberto: um professor B conseguia ler/editar/apagar o material do professor A
porque as rotas usam só ``require_role("ADMIN","TEACHER","INSTRUCTOR")``, sem
comparar o dono. SEC-SCOPE-8 adiciona os helpers
``assert_teacher_owns_{course,chapter,content,question}`` (``authz.py``), que sobem
a cadeia ``content -> chapter -> course -> discipline_teachers`` e reusam
``assert_teacher_owns_discipline``.

Ownership chain seeded here (on top of the conftest base seed)
==============================================================
* ``DISCIPLINE_ID`` (conftest) is owned by ``TEACHER_ID`` (Teacher A).
* A second teacher, ``TEACHER_B_ID``, owns ``DISCIPLINE_B_ID``.
* Teacher A's tree:  COURSE_A -> CHAPTER_A -> CONTENT_A -> QUESTION_A.
* Every cross-actor test authenticates as Teacher B and pokes at Teacher A's
  rows; the 3-outcome contract (owner passes / cross actor 403-404 + no mutation)
  is asserted via the shared ``idor_helpers``.

The harness is the shared in-memory fake from ``conftest.py`` (never edited here):
``.eq``/``.maybe_single``/``insert``/``update``/``delete`` are all supported, so
the authz gates — which load the row and walk the FK chain — run end-to-end.
"""
from __future__ import annotations

import pytest

from conftest import (
    ADMIN_ID,
    DISCIPLINE_ID,
    TEACHER_ID,
    _user,
)
from idor_helpers import (
    assert_cross_actor_forbidden_no_mutation,
    assert_owner_passes,
)

# ── Teacher B (the cross actor) + his own discipline ────────────────────────
TEACHER_B_ID = "teacher-b"
DISCIPLINE_B_ID = "discipline-b"

# ── Teacher A's content tree (rooted at conftest DISCIPLINE_ID) ─────────────
COURSE_A = "course-a"
CHAPTER_A = "chapter-a"
CONTENT_A = "content-a"
QUESTION_A = "question-a"

# ── An orphan course with NO discipline_id (legacy row, fail-closed path) ───
COURSE_ORPHAN = "course-orphan"


def _seed_tree(fake):
    """Seed Teacher A's owned course tree + Teacher B's separate discipline."""
    # Teacher B exists and owns his own (unrelated) discipline.
    fake.add("users", _user(TEACHER_B_ID, "TEACHER", "Teacher B"))
    fake.add("disciplines", {"id": DISCIPLINE_B_ID, "title": "Teacher B Discipline"})
    fake.add("discipline_teachers", {"discipline_id": DISCIPLINE_B_ID, "teacher_id": TEACHER_B_ID})

    # Teacher A's tree, pinned to DISCIPLINE_ID (owned by TEACHER_ID via conftest).
    fake.add("courses", {"id": COURSE_A, "title": "Curso A", "discipline_id": DISCIPLINE_ID,
                         "status": "active"})
    fake.add("chapters", {"id": CHAPTER_A, "course_id": COURSE_A, "title": "Cap A", "order": 1})
    fake.add("contents", {"id": CONTENT_A, "chapter_id": CHAPTER_A, "title": "Cont A",
                          "content_type": "text", "order": 1})
    fake.add("questions", {"id": QUESTION_A, "content_id": CONTENT_A, "question_text": "Q A?"})

    # A legacy orphan course with no discipline_id at all.
    fake.add("courses", {"id": COURSE_ORPHAN, "title": "Órfão", "discipline_id": None,
                         "status": "active"})


@pytest.fixture
def as_teacher_b(app):
    """Authenticate as Teacher B — the canonical cross-teacher actor."""
    from conftest import _user as make_user  # local alias for clarity
    user = make_user(TEACHER_B_ID, "TEACHER", "Teacher B")
    from auth import get_current_user
    app.dependency_overrides[get_current_user] = lambda: dict(user)
    return user


# ===========================================================================
# The 4 destructive endpoints the story mandates (AC3).
# ===========================================================================
class TestDestructiveEndpointsCrossTeacherBlocked:
    # ── PUT /courses/{id} ───────────────────────────────────
    def test_update_course_owner_passes(self, client, as_teacher, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.put(f"/courses/{COURSE_A}", json={"title": "Editado pelo dono"})
        assert_owner_passes(resp)
        assert fake_supabase.find("courses", id=COURSE_A)["title"] == "Editado pelo dono"

    def test_update_course_cross_teacher_forbidden_no_mutation(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.put(f"/courses/{COURSE_A}", json={"title": "HIJACK"})
        assert_cross_actor_forbidden_no_mutation(
            resp, fake_supabase, table="courses", victim_row_id=COURSE_A
        )
        assert fake_supabase.find("courses", id=COURSE_A)["title"] == "Curso A"

    # ── DELETE /chapters/{id} ───────────────────────────────
    def test_delete_chapter_owner_passes(self, client, as_teacher, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.delete(f"/chapters/{CHAPTER_A}")
        assert_owner_passes(resp)
        assert fake_supabase.find("chapters", id=CHAPTER_A) is None

    def test_delete_chapter_cross_teacher_forbidden_no_mutation(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.delete(f"/chapters/{CHAPTER_A}")
        assert_cross_actor_forbidden_no_mutation(
            resp, fake_supabase, table="chapters", victim_row_id=CHAPTER_A
        )
        assert fake_supabase.find("chapters", id=CHAPTER_A) is not None

    # ── DELETE /contents/{id} ───────────────────────────────
    def test_delete_content_owner_passes(self, client, as_teacher, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.delete(f"/contents/{CONTENT_A}")
        assert_owner_passes(resp)
        assert fake_supabase.find("contents", id=CONTENT_A) is None

    def test_delete_content_cross_teacher_forbidden_no_mutation(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.delete(f"/contents/{CONTENT_A}")
        assert_cross_actor_forbidden_no_mutation(
            resp, fake_supabase, table="contents", victim_row_id=CONTENT_A
        )
        assert fake_supabase.find("contents", id=CONTENT_A) is not None

    # ── PUT /contents/{id}/questions/batch ──────────────────
    def test_batch_update_questions_owner_passes(self, client, as_teacher, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.put(
            f"/contents/{CONTENT_A}/questions/batch",
            json={"items": [{"question_text": "Nova Q?"}]},
        )
        assert_owner_passes(resp)

    def test_batch_update_questions_cross_teacher_forbidden_no_wipe(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.put(
            f"/contents/{CONTENT_A}/questions/batch",
            json={"items": [{"question_text": "HIJACK?"}]},
        )
        assert resp.status_code in (403, 404)
        # The delete+recreate must NOT have run: Teacher A's question survives and
        # no insert/delete landed on the victim content's questions.
        assert fake_supabase.find("questions", id=QUESTION_A) is not None
        assert all(m["table"] != "questions" for m in fake_supabase.mutations)


# ===========================================================================
# ADMIN keeps unrestricted access (AC2).
# ===========================================================================
class TestAdminUnrestricted:
    def test_admin_updates_any_course(self, client, as_admin, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.put(f"/courses/{COURSE_A}", json={"title": "Admin editou"})
        assert resp.status_code == 200
        assert fake_supabase.find("courses", id=COURSE_A)["title"] == "Admin editou"

    def test_admin_deletes_any_content(self, client, as_admin, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.delete(f"/contents/{CONTENT_A}")
        assert resp.status_code == 200
        assert fake_supabase.find("contents", id=CONTENT_A) is None

    def test_admin_batch_updates_any_content_questions(self, client, as_admin, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.put(
            f"/contents/{CONTENT_A}/questions/batch",
            json={"items": [{"question_text": "Admin Q?"}]},
        )
        assert resp.status_code == 200


# ===========================================================================
# Owning teacher keeps full access across the whole tree (regression floor).
# ===========================================================================
class TestOwnerFullTree:
    def test_owner_updates_chapter(self, client, as_teacher, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.put(f"/chapters/{CHAPTER_A}", json={"title": "Cap editado"})
        assert resp.status_code == 200

    def test_owner_updates_content(self, client, as_teacher, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.put(f"/contents/{CONTENT_A}", json={"title": "Cont editado"})
        assert resp.status_code == 200

    def test_owner_deletes_question(self, client, as_teacher, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.delete(f"/questions/{QUESTION_A}")
        assert resp.status_code == 200
        assert fake_supabase.find("questions", id=QUESTION_A) is None


# ===========================================================================
# Cross-teacher blocked on the remaining write/create endpoints.
# ===========================================================================
class TestCrossTeacherWritesBlocked:
    def test_update_chapter_cross_teacher_forbidden(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.put(f"/chapters/{CHAPTER_A}", json={"title": "HIJACK"})
        assert_cross_actor_forbidden_no_mutation(
            resp, fake_supabase, table="chapters", victim_row_id=CHAPTER_A
        )
        assert fake_supabase.find("chapters", id=CHAPTER_A)["title"] == "Cap A"

    def test_update_content_cross_teacher_forbidden(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.put(f"/contents/{CONTENT_A}", json={"title": "HIJACK"})
        assert_cross_actor_forbidden_no_mutation(
            resp, fake_supabase, table="contents", victim_row_id=CONTENT_A
        )
        assert fake_supabase.find("contents", id=CONTENT_A)["title"] == "Cont A"

    def test_delete_question_cross_teacher_forbidden(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.delete(f"/questions/{QUESTION_A}")
        assert_cross_actor_forbidden_no_mutation(
            resp, fake_supabase, table="questions", victim_row_id=QUESTION_A
        )
        assert fake_supabase.find("questions", id=QUESTION_A) is not None

    def test_update_question_cross_teacher_forbidden(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.put(f"/questions/{QUESTION_A}", json={"question_text": "HIJACK?"})
        assert_cross_actor_forbidden_no_mutation(
            resp, fake_supabase, table="questions", victim_row_id=QUESTION_A
        )
        assert fake_supabase.find("questions", id=QUESTION_A)["question_text"] == "Q A?"

    def test_create_chapter_under_foreign_course_forbidden(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.post(f"/courses/{COURSE_A}/chapters", json={"title": "intruso", "order": 9})
        assert resp.status_code in (403, 404)
        # No chapter was inserted under Teacher A's course.
        assert all(m["table"] != "chapters" or m["op"] != "insert" for m in fake_supabase.mutations)

    def test_create_content_under_foreign_chapter_forbidden(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.post(
            f"/chapters/{CHAPTER_A}/contents",
            json={"title": "intruso", "content_type": "text", "order": 9},
        )
        assert resp.status_code in (403, 404)
        assert all(m["table"] != "contents" or m["op"] != "insert" for m in fake_supabase.mutations)


# ===========================================================================
# Cross-teacher blocked on the shared (get_current_user) READS.
# ===========================================================================
class TestCrossTeacherReadsBlocked:
    def test_get_course_cross_teacher_forbidden(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.get(f"/courses/{COURSE_A}")
        assert resp.status_code in (403, 404)
        assert "chapters" not in resp.json()

    def test_export_course_cross_teacher_forbidden(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.get(f"/courses/{COURSE_A}/export")
        assert resp.status_code in (403, 404)

    def test_get_content_cross_teacher_forbidden_no_leak(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.get(f"/contents/{CONTENT_A}")
        assert resp.status_code in (403, 404)
        assert "questions" not in resp.json()

    def test_list_questions_cross_teacher_forbidden(self, client, as_teacher_b, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.get(f"/contents/{CONTENT_A}/questions")
        assert resp.status_code in (403, 404)

    def test_owner_reads_own_course(self, client, as_teacher, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.get(f"/courses/{COURSE_A}")
        assert resp.status_code == 200
        assert resp.json()["id"] == COURSE_A


# ===========================================================================
# Fail-closed on legacy orphan courses (no discipline_id) for non-owners.
# ===========================================================================
class TestOrphanCourseFailClosed:
    def test_teacher_cannot_edit_orphan_course(self, client, as_teacher_b, fake_supabase):
        # An orphan course (discipline_id=None) must be denied to any teacher —
        # there is no discipline to scope against, so we fail closed.
        _seed_tree(fake_supabase)
        fake_supabase.reset_mutations()
        resp = client.put(f"/courses/{COURSE_ORPHAN}", json={"title": "HIJACK"})
        assert resp.status_code == 403
        assert all(m["table"] != "courses" for m in fake_supabase.mutations)

    def test_owning_teacher_also_blocked_on_orphan(self, client, as_teacher, fake_supabase):
        # Even Teacher A (owner of DISCIPLINE_ID) has no claim on a course with no
        # discipline — fail-closed applies to every non-ADMIN teacher.
        _seed_tree(fake_supabase)
        resp = client.put(f"/courses/{COURSE_ORPHAN}", json={"title": "x"})
        assert resp.status_code == 403

    def test_admin_can_edit_orphan_course(self, client, as_admin, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.put(f"/courses/{COURSE_ORPHAN}", json={"title": "Admin"})
        assert resp.status_code == 200


# ===========================================================================
# 404 vs 403 hygiene: a missing resource does not disclose existence.
# ===========================================================================
class TestMissingResourceHygiene:
    def test_update_missing_course_404_for_teacher(self, client, as_teacher, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.put("/courses/does-not-exist", json={"title": "x"})
        assert resp.status_code == 404

    def test_delete_missing_chapter_404_for_teacher(self, client, as_teacher, fake_supabase):
        _seed_tree(fake_supabase)
        resp = client.delete("/chapters/does-not-exist")
        assert resp.status_code == 404
