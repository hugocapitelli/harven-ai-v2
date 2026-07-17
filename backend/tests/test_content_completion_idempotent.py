"""P0 fix 5 — real per-student progress: idempotent completion per (user, content).

``complete-content`` only bumped a counter in ``course_progress`` — it never
recorded WHICH content was finished, so repeat-clicking the same content inflated
progress toward 100% and no one could audit a student's actual trail. Pinned here:

  * first completion inserts a ``content_completions`` row and bumps the counter;
  * replaying the SAME content is a no-op: counter frozen, no duplicate activity
    points, response flags ``already_completed``;
  * a DIFFERENT content still advances the counter;
  * a DB missing the new table degrades to the legacy counter-only behavior
    (200, not 503).
"""
from __future__ import annotations

from conftest import STUDENT_A_ID

COURSE_ID = "course-gamify"
URL = f"/users/{STUDENT_A_ID}/courses/{COURSE_ID}/complete-content"


def _seed_course(fake, n_contents: int = 3):
    fake.add("courses", {"id": COURSE_ID, "title": "Curso"})
    fake.add("chapters", {"id": "chap-1", "course_id": COURSE_ID})
    for i in range(1, n_contents + 1):
        fake.add("contents", {"id": f"content-{i}", "chapter_id": "chap-1", "title": f"Aula {i}"})


def _completions(fake):
    return [
        r for r in fake.rows("content_completions")
        if r["user_id"] == STUDENT_A_ID
    ]


def _activities(fake):
    return [
        r for r in fake.rows("user_activities")
        if r["user_id"] == STUDENT_A_ID and r.get("activity_type") == "content_completed"
    ]


class TestIdempotentCompletion:
    def test_first_completion_records_row_and_bumps_counter(self, client, as_student, fake_supabase):
        _seed_course(fake_supabase)

        resp = client.post(f"{URL}/content-1")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["completed_contents"] == 1
        assert body["total_contents"] == 3

        rows = _completions(fake_supabase)
        assert len(rows) == 1
        assert rows[0]["content_id"] == "content-1"
        assert rows[0]["course_id"] == COURSE_ID

    def test_replay_same_content_does_not_inflate_progress(self, client, as_student, fake_supabase):
        _seed_course(fake_supabase)

        first = client.post(f"{URL}/content-1").json()
        replay = client.post(f"{URL}/content-1")
        assert replay.status_code == 200, replay.text
        body = replay.json()

        assert body["already_completed"] is True
        assert body["completed_contents"] == first["completed_contents"] == 1
        assert len(_completions(fake_supabase)) == 1
        # No duplicate gamification points either.
        assert len(_activities(fake_supabase)) == 1

    def test_distinct_contents_advance_progress(self, client, as_student, fake_supabase):
        _seed_course(fake_supabase)

        client.post(f"{URL}/content-1")
        resp = client.post(f"{URL}/content-2")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["completed_contents"] == 2
        assert {r["content_id"] for r in _completions(fake_supabase)} == {"content-1", "content-2"}

    def test_concurrent_duplicate_insert_is_swallowed(self, client, as_student, fake_supabase, monkeypatch):
        """Race path: two simultaneous clicks — the SELECT pre-check of the loser
        misses (row not yet visible), then its INSERT hits the UNIQUE index. The
        violation must be treated as already-completed, never a 500, and the
        counter must NOT be bumped by the loser."""
        _seed_course(fake_supabase)
        original_table = fake_supabase.table

        def table(name):
            qb = original_table(name)
            if name != "content_completions":
                return qb
            orig = qb.execute

            def execute():
                if qb._op == "select":
                    # The winner's row is not visible to the loser's pre-check yet.
                    from fakes import _Result
                    return _Result(data=[])
                if qb._op == "insert":
                    raise Exception(
                        'duplicate key value violates unique constraint '
                        '"content_completions_user_id_content_id_key" (23505)'
                    )
                return orig()

            qb.execute = execute
            return qb

        monkeypatch.setattr(fake_supabase, "table", table)

        resp = client.post(f"{URL}/content-1")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["already_completed"] is True
        assert body["completed_contents"] == 0  # loser never bumps the counter
        assert len(_activities(fake_supabase)) == 0  # and never double-awards points


class TestGracefulDegradationWithoutTable:
    def test_missing_completions_table_falls_back_to_counter(self, app, client, as_student, fake_supabase, monkeypatch):
        _seed_course(fake_supabase)

        original_table = fake_supabase.table

        def table(name):
            if name == "content_completions":
                qb = original_table(name)

                def boom():
                    raise Exception('relation "content_completions" does not exist')

                qb.execute = boom
                return qb
            return original_table(name)

        monkeypatch.setattr(fake_supabase, "table", table)

        resp = client.post(f"{URL}/content-1")
        assert resp.status_code == 200, resp.text
        assert resp.json()["completed_contents"] == 1
