"""DATA-GAM-3 — integration tests for scoring on the completion edge.

Proves, against the in-memory ``FakeSupabaseClient``, that:
* completing a scorable session persists a non-null ``performance_score`` in
  ``chat_sessions`` (the gamification dashboards now read a real value, not 0);
* completing a session with no student signal leaves ``performance_score`` NULL
  (an honest absence, never a forced 0 that would poison averages);
* a second ``/complete`` is an idempotent no-op that does NOT recompute or
  re-write the score (compatible with DATA-GAM-4).
"""
from conftest import SESSION_A_ID, SESSION_B_ID, STUDENT_A_ID, STUDENT_B_ID


def _seed_substantive_dialogue(fake, session_id):
    """Replace the session's messages with a full substantive student dialogue so
    the engagement fallback yields a high, non-null score."""
    fake.seed(
        "chat_messages",
        [
            {"id": "m1", "session_id": session_id, "role": "user",
             "content": "Primeira resposta desenvolvida com argumento claro.",
             "created_at": "2026-01-01T00:00:01Z"},
            {"id": "m2", "session_id": session_id, "role": "assistant",
             "content": "Boa. E por quê?", "agent_type": "socrates",
             "created_at": "2026-01-01T00:00:02Z"},
            {"id": "m3", "session_id": session_id, "role": "user",
             "content": "Segunda resposta aprofundando o raciocinio.",
             "created_at": "2026-01-01T00:00:03Z"},
            {"id": "m4", "session_id": session_id, "role": "assistant",
             "content": "Interessante, continue.", "agent_type": "socrates",
             "created_at": "2026-01-01T00:00:04Z"},
            {"id": "m5", "session_id": session_id, "role": "user",
             "content": "Terceira resposta conectando os conceitos discutidos.",
             "created_at": "2026-01-01T00:00:05Z"},
            {"id": "m6", "session_id": session_id, "role": "user",
             "content": "Quarta resposta concluindo a discussao com sintese.",
             "created_at": "2026-01-01T00:00:06Z"},
        ],
    )


class TestScoreOnCompletion:
    def test_completing_scorable_session_persists_score(
        self, client, as_student, fake_supabase
    ):
        _seed_substantive_dialogue(fake_supabase, SESSION_A_ID)

        resp = client.put(f"/chat-sessions/{SESSION_A_ID}/complete")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

        row = fake_supabase.find("chat_sessions", id=SESSION_A_ID)
        assert row["status"] == "completed"
        score = row.get("performance_score")
        assert score is not None, "scorable session must persist a non-null score"
        assert 0 < score <= 100, f"dashboard-visible score must be in (0,100]: {score}"

    def test_completing_session_with_no_student_signal_leaves_score_null(
        self, client, as_student, fake_supabase
    ):
        # Session A owned by STUDENT_A. GRD-2: completion now REQUIRES at least one
        # real student turn (a 0-user-turn session can no longer be completed — that
        # was the phantom-session bug). So the "no scorable signal" case is a session
        # where the student DID interact but the turn carries no substantive content
        # (empty answer) — scoring honestly yields NULL, yet completion is allowed
        # because a real ``role='user'`` turn exists.
        fake_supabase.seed(
            "chat_messages",
            [
                {"id": "t1", "session_id": SESSION_A_ID, "role": "assistant",
                 "content": "Qual sua leitura?", "agent_type": "socrates",
                 "created_at": "2026-01-01T00:00:01Z"},
                {"id": "t2", "session_id": SESSION_A_ID, "role": "user",
                 "content": "   ", "created_at": "2026-01-01T00:00:02Z"},
            ],
        )

        resp = client.put(f"/chat-sessions/{SESSION_A_ID}/complete")
        assert resp.status_code == 200

        row = fake_supabase.find("chat_sessions", id=SESSION_A_ID)
        assert row["status"] == "completed"
        # Honest absence: NULL, not a forced 0 (empty student content is unscorable).
        assert row.get("performance_score") is None

    def test_second_complete_does_not_recompute_score(
        self, client, as_student, fake_supabase
    ):
        _seed_substantive_dialogue(fake_supabase, SESSION_A_ID)

        first = client.put(f"/chat-sessions/{SESSION_A_ID}/complete")
        assert first.status_code == 200
        original_score = fake_supabase.find(
            "chat_sessions", id=SESSION_A_ID
        ).get("performance_score")
        assert original_score is not None

        # Mutate the transcript AFTER completion; a correct idempotent path must
        # NOT re-read/re-score it.
        fake_supabase.seed("chat_messages", [])
        fake_supabase.reset_mutations()

        second = client.put(f"/chat-sessions/{SESSION_A_ID}/complete")
        assert second.status_code == 200
        assert second.json()["status"] == "completed"

        # No re-write at all on the idempotent path.
        updates = [
            m for m in fake_supabase.mutations
            if m["op"] == "update" and m["table"] == "chat_sessions"
        ]
        assert updates == [], f"re-complete must not recompute/re-write: {updates}"

        # Score is preserved exactly (written once, on the first transition).
        assert (
            fake_supabase.find("chat_sessions", id=SESSION_A_ID).get("performance_score")
            == original_score
        )

    def test_score_computation_failure_does_not_block_completion(
        self, client, as_student, fake_supabase, monkeypatch
    ):
        # If scoring raises, completion (the primary op) must still succeed and the
        # score is simply left NULL (additive, best-effort).
        _seed_substantive_dialogue(fake_supabase, SESSION_A_ID)

        import routes_ai

        def _boom(_turns):
            raise RuntimeError("scoring exploded")

        monkeypatch.setattr(routes_ai, "compute_performance_score", _boom)

        resp = client.put(f"/chat-sessions/{SESSION_A_ID}/complete")
        assert resp.status_code == 200
        row = fake_supabase.find("chat_sessions", id=SESSION_A_ID)
        assert row["status"] == "completed"
        assert row.get("performance_score") is None
