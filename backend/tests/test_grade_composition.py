"""GRD-1 — composed grade aggregation contract.

The Quadro de Notas is no longer a place to type a grade per course: a student's
course grade is the MEAN of the per-session ``session_reviews.rating`` the teacher
gave to each Socratic interaction, and the overall average is the mean of those
per-course grades. The gradebook endpoint
(``GET /disciplines/{id}/gradebook``) is the single source of truth for that
composition.

This module proves the pipeline end to end against the in-process
``FakeSupabaseClient`` (no network / no DB), using the shared harness from
``conftest.py`` (never edited):

  * AC3 (composition): N sessions with distinct ratings for the same
    student×course aggregate to the correct ``avg_rating``; ``final_grade`` equals
    ``avg_rating`` when there is no override; ``overall_avg`` is the mean of the
    per-course ``final_grade``s.
  * AC3 (no ratings): a course with no rated session yields ``avg_rating: None``
    and does NOT drag the ``overall_avg``.
  * AC3 (live proof): creating a review via ``POST /chat-sessions/{id}/review``
    with a rating changes the student's ``avg_rating``/``overall_avg`` — grades
    move without any manual typing.
  * Drill-down (AC2 support): ``GET /disciplines/{id}/sessions?student_id=...``
    filters to one student and enriches each row with course/chapter/content
    titles + the existing rating.

The composition arithmetic mirrors ``discipline_gradebook`` exactly; the tests
assert the observable HTTP contract, not the implementation.
"""
from __future__ import annotations

import pytest

from conftest import (  # noqa: F401 (seed ids reused for clarity)
    ADMIN_ID,
    STUDENT_A_ID,
    STUDENT_B_ID,
    TEACHER_ID,
    make_seed_tables,
)
from fakes import FakeSupabaseClient

# ---------------------------------------------------------------------------
# A discipline with a full content->chapter->course chain and rated sessions.
# ---------------------------------------------------------------------------
DISC_ID = "disc-grd"
COURSE_1 = "course-grd-1"
COURSE_2 = "course-grd-2"
CHAPTER_1 = "chap-grd-1"
CHAPTER_2 = "chap-grd-2"
CONTENT_1A = "content-grd-1a"   # course 1
CONTENT_1B = "content-grd-1b"   # course 1
CONTENT_2A = "content-grd-2a"   # course 2


def _grade_seed() -> dict:
    """Seed: STUDENT_A enrolled in DISC_ID; 3 rated sessions in course 1
    (ratings 8, 6, 10 -> avg 8.0) + 1 rated session in course 2 (rating 5)."""
    tables = make_seed_tables()
    tables["disciplines"].append({"id": DISC_ID, "name": "Composed Grades"})
    tables["discipline_teachers"].append({"discipline_id": DISC_ID, "teacher_id": TEACHER_ID})
    tables["discipline_students"] = [{"discipline_id": DISC_ID, "student_id": STUDENT_A_ID}]

    tables["courses"] = [
        {"id": COURSE_1, "discipline_id": DISC_ID, "title": "Curso Um"},
        {"id": COURSE_2, "discipline_id": DISC_ID, "title": "Curso Dois"},
    ]
    tables["chapters"] = [
        {"id": CHAPTER_1, "course_id": COURSE_1, "title": "Cap 1"},
        {"id": CHAPTER_2, "course_id": COURSE_2, "title": "Cap 2"},
    ]
    tables["contents"] = [
        {"id": CONTENT_1A, "chapter_id": CHAPTER_1, "title": "Conteudo 1A"},
        {"id": CONTENT_1B, "chapter_id": CHAPTER_1, "title": "Conteudo 1B"},
        {"id": CONTENT_2A, "chapter_id": CHAPTER_2, "title": "Conteudo 2A"},
    ]
    tables["chat_sessions"] = [
        {"id": "sess-1a", "user_id": STUDENT_A_ID, "content_id": CONTENT_1A,
         "status": "completed", "total_messages": 4, "created_at": "2026-01-01T00:00:00Z"},
        {"id": "sess-1b", "user_id": STUDENT_A_ID, "content_id": CONTENT_1A,
         "status": "completed", "total_messages": 5, "created_at": "2026-01-02T00:00:00Z"},
        {"id": "sess-1c", "user_id": STUDENT_A_ID, "content_id": CONTENT_1B,
         "status": "completed", "total_messages": 3, "created_at": "2026-01-03T00:00:00Z"},
        {"id": "sess-2a", "user_id": STUDENT_A_ID, "content_id": CONTENT_2A,
         "status": "completed", "total_messages": 6, "created_at": "2026-01-04T00:00:00Z"},
    ]
    tables["session_reviews"] = [
        {"id": "rev-1a", "session_id": "sess-1a", "reviewer_id": TEACHER_ID, "rating": 8, "status": "reviewed"},
        {"id": "rev-1b", "session_id": "sess-1b", "reviewer_id": TEACHER_ID, "rating": 6, "status": "reviewed"},
        {"id": "rev-1c", "session_id": "sess-1c", "reviewer_id": TEACHER_ID, "rating": 10, "status": "reviewed"},
        {"id": "rev-2a", "session_id": "sess-2a", "reviewer_id": TEACHER_ID, "rating": 5, "status": "reviewed"},
    ]
    tables["grade_overrides"] = []
    return tables


@pytest.fixture
def graded_fake() -> FakeSupabaseClient:
    return FakeSupabaseClient(_grade_seed())


@pytest.fixture
def graded_app(graded_fake, monkeypatch):
    """The FastAPI app backed by the grade-seeded fake (same wiring as conftest.app)."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 48)

    import config
    config.get_settings.cache_clear()

    import database
    import main
    from database import get_supabase

    monkeypatch.setattr(database, "get_supabase", lambda: graded_fake)
    monkeypatch.setattr(main, "get_supabase", lambda: graded_fake, raising=False)
    main.app.dependency_overrides[get_supabase] = lambda: graded_fake
    if hasattr(main.app.state, "limiter"):
        main.app.state.limiter.enabled = False

    yield main.app
    main.app.dependency_overrides.pop(get_supabase, None)


@pytest.fixture
def graded_client(graded_app):
    from fastapi.testclient import TestClient
    return TestClient(graded_app)


def _act_as(graded_app, uid, role):
    from auth import get_current_user
    graded_app.dependency_overrides[get_current_user] = lambda: {
        "id": uid, "role": role, "name": uid, "email": f"{uid}@harven.ai",
    }


def _student_row(payload, student_id):
    for s in payload["students"]:
        if s["id"] == student_id:
            return s
    raise AssertionError(f"student {student_id} not in gradebook")


def _course(student_row, course_id):
    for c in student_row["courses"]:
        if c["course_id"] == course_id:
            return c
    raise AssertionError(f"course {course_id} not in student row")


# ===========================================================================
# AC3 — composition arithmetic
# ===========================================================================
class TestGradeComposition:
    def test_avg_rating_is_mean_of_session_ratings(self, graded_client, graded_app):
        _act_as(graded_app, TEACHER_ID, "TEACHER")
        resp = graded_client.get(f"/disciplines/{DISC_ID}/gradebook")
        assert resp.status_code == 200, resp.text
        student = _student_row(resp.json(), STUDENT_A_ID)

        # Course 1: ratings 8, 6, 10 -> mean 8.0
        c1 = _course(student, COURSE_1)
        assert c1["avg_rating"] == 8.0
        assert c1["override_grade"] is None
        assert c1["final_grade"] == 8.0  # no override -> final == avg

        # Course 2: single rating 5 -> mean 5.0
        c2 = _course(student, COURSE_2)
        assert c2["avg_rating"] == 5.0
        assert c2["final_grade"] == 5.0

    def test_overall_avg_is_mean_of_course_final_grades(self, graded_client, graded_app):
        _act_as(graded_app, TEACHER_ID, "TEACHER")
        resp = graded_client.get(f"/disciplines/{DISC_ID}/gradebook")
        student = _student_row(resp.json(), STUDENT_A_ID)
        # final grades: course1=8.0, course2=5.0 -> overall (8+5)/2 = 6.5
        assert student["overall_avg"] == 6.5

    def test_course_without_rated_session_is_none_and_excluded_from_overall(
        self, graded_fake, graded_client, graded_app
    ):
        # Add a 3rd course with NO rated session; its avg_rating must be None and
        # it must NOT drag overall_avg (which stays the mean of the rated courses).
        graded_fake.add("courses", {"id": "course-grd-3", "discipline_id": DISC_ID, "title": "Curso Tres"})
        graded_fake.add("chapters", {"id": "chap-grd-3", "course_id": "course-grd-3", "title": "Cap 3"})
        graded_fake.add("contents", {"id": "content-grd-3a", "chapter_id": "chap-grd-3", "title": "Conteudo 3A"})

        _act_as(graded_app, TEACHER_ID, "TEACHER")
        resp = graded_client.get(f"/disciplines/{DISC_ID}/gradebook")
        student = _student_row(resp.json(), STUDENT_A_ID)

        c3 = _course(student, "course-grd-3")
        assert c3["avg_rating"] is None
        assert c3["final_grade"] is None
        # overall_avg unchanged: still (8.0 + 5.0) / 2 = 6.5, the None course excluded.
        assert student["overall_avg"] == 6.5


# ===========================================================================
# AC3 — live proof: rating a session moves the gradebook (no manual typing)
# ===========================================================================
class TestRatingReflectsInGradebook:
    def test_creating_review_changes_avg_and_overall(self, graded_fake, graded_client, graded_app):
        # A 4th session in course 1 exists but is NOT yet rated -> course1 avg is 8.0.
        graded_fake.add("chat_sessions", {
            "id": "sess-1d", "user_id": STUDENT_A_ID, "content_id": CONTENT_1B,
            "status": "completed", "total_messages": 2, "created_at": "2026-01-05T00:00:00Z",
        })

        _act_as(graded_app, TEACHER_ID, "TEACHER")
        before = _student_row(graded_client.get(f"/disciplines/{DISC_ID}/gradebook").json(), STUDENT_A_ID)
        assert _course(before, COURSE_1)["avg_rating"] == 8.0  # 8,6,10
        assert before["overall_avg"] == 6.5

        # Teacher rates the previously-unrated session with a 2.
        r = graded_client.post("/chat-sessions/sess-1d/review", json={"rating": 2, "feedback": "raso"})
        assert r.status_code == 201, r.text

        after = _student_row(graded_client.get(f"/disciplines/{DISC_ID}/gradebook").json(), STUDENT_A_ID)
        # Course 1 now averages 8,6,10,2 -> 6.5
        assert _course(after, COURSE_1)["avg_rating"] == 6.5
        # Overall: (6.5 + 5.0) / 2 = 5.75
        assert after["overall_avg"] == 5.75


# ===========================================================================
# AC2 support — per-student drill-down enrichment
# ===========================================================================
class TestStudentSessionsDrillDown:
    def test_student_filter_scopes_and_enriches(self, graded_fake, graded_client, graded_app):
        # Add a session for STUDENT_B so the student_id filter has something to exclude.
        graded_fake.add("discipline_students", {"discipline_id": DISC_ID, "student_id": STUDENT_B_ID})
        graded_fake.add("chat_sessions", {
            "id": "sess-b", "user_id": STUDENT_B_ID, "content_id": CONTENT_1A,
            "status": "active", "total_messages": 1, "created_at": "2026-01-06T00:00:00Z",
        })

        _act_as(graded_app, TEACHER_ID, "TEACHER")
        resp = graded_client.get(f"/disciplines/{DISC_ID}/sessions", params={"student_id": STUDENT_A_ID})
        assert resp.status_code == 200, resp.text
        rows = resp.json()["data"]

        # Only STUDENT_A's sessions (4 seeded), STUDENT_B excluded.
        assert rows, "expected sessions for STUDENT_A"
        assert all(row["user_id"] == STUDENT_A_ID for row in rows)
        assert not any(row["id"] == "sess-b" for row in rows)

        # Enrichment present: course/chapter/content titles + rating resolved.
        by_id = {row["id"]: row for row in rows}
        s1a = by_id["sess-1a"]
        assert s1a["course_id"] == COURSE_1
        assert s1a["course_title"] == "Curso Um"
        assert s1a["chapter_title"] == "Cap 1"
        assert s1a["content_title"] == "Conteudo 1A"
        assert s1a["rating"] == 8

    def test_unfiltered_sessions_still_return_all_students(self, graded_fake, graded_client, graded_app):
        # Regression: the discipline-wide "Conversas" tab (no student_id) is unchanged.
        graded_fake.add("discipline_students", {"discipline_id": DISC_ID, "student_id": STUDENT_B_ID})
        graded_fake.add("chat_sessions", {
            "id": "sess-b", "user_id": STUDENT_B_ID, "content_id": CONTENT_1A,
            "status": "active", "total_messages": 1, "created_at": "2026-01-06T00:00:00Z",
        })
        _act_as(graded_app, TEACHER_ID, "TEACHER")
        resp = graded_client.get(f"/disciplines/{DISC_ID}/sessions")
        assert resp.status_code == 200, resp.text
        user_ids = {row["user_id"] for row in resp.json()["data"]}
        assert STUDENT_A_ID in user_ids and STUDENT_B_ID in user_ids
