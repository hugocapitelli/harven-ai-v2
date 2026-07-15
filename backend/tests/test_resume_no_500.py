"""GRD-5 — the chat resume path must never 500 on a legitimate empty state.

Symptom (Hugo, production build): ``Chat resume error: AxiosError 500`` on the
``messages`` resource, from ``ChapterReader``'s resume hydration. Root cause:
supabase-py / postgrest 2.28.x return ``None`` (the whole response object, NOT
``_Result(data=None)``) from ``.maybe_single().execute()`` when ZERO rows match.
``get_session_by_content`` read ``result.data`` unconditionally, so a chapter the
student has NO session for (the common case on a fresh open) raised
``AttributeError: 'NoneType' object has no attribute 'data'`` → HTTP 500 instead of
the intended 404. The frontend's ``byContent(...).catch(() => null)`` treats 404 as
"no session yet", but a 500 surfaces as the resume error. Precedent: commit 5847a60
(same None-guard in ``BaseRepository.get_by_id``).

The in-memory ``FakeSupabaseClient`` was made faithful (zero-row
``.maybe_single().execute()`` → ``None``), so these tests reproduce the real 500
before the guard and pass after. Runs headless via the shared conftest harness.
"""
from __future__ import annotations

from conftest import STUDENT_A_ID, SESSION_A_ID


class TestResumeByContentNo500:
    def test_by_content_with_no_session_returns_404_not_500(self, client, as_student):
        # STUDENT_A has NO chat session for this content → zero rows → the endpoint
        # must resolve to 404 (handled by the frontend as "no session"), never 500.
        resp = client.get("/chat-sessions/by-content/content-with-no-session")
        assert resp.status_code == 404, (
            f"empty by-content must be 404, got {resp.status_code}: {resp.text}"
        )

    def test_by_content_with_existing_session_returns_it(self, client, as_student, fake_supabase):
        fake_supabase.add("chat_sessions", {
            "id": "sess-resume", "user_id": STUDENT_A_ID, "content_id": "content-resume",
            "status": "active", "total_messages": 2, "initial_question_text": "Q",
            "created_at": "2026-01-01T00:00:00Z",
        })
        resp = client.get("/chat-sessions/by-content/content-resume")
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == "sess-resume"

    def test_by_content_multi_row_returns_newest_not_500(self, client, as_student, fake_supabase):
        # Post-restart / phantom state: >1 session for the pair. ``.order().limit(1)``
        # must resolve the newest cleanly (no PGRST116, no None crash).
        for i, ts in enumerate(["2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z"]):
            fake_supabase.add("chat_sessions", {
                "id": f"sess-multi-{i}", "user_id": STUDENT_A_ID, "content_id": "content-multi",
                "status": "completed", "total_messages": 4, "initial_question_text": "Q",
                "created_at": ts,
            })
        resp = client.get("/chat-sessions/by-content/content-multi")
        assert resp.status_code == 200, resp.text
        assert resp.json()["id"] == "sess-multi-1"  # newest

    def test_get_messages_on_missing_session_is_404_not_500(self, client, as_student):
        # The resume also GETs messages; a missing session id must be 404 (via
        # load_session_or_404's None-guard), never 500.
        resp = client.get("/chat-sessions/does-not-exist/messages")
        assert resp.status_code == 404, resp.text
