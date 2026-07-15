"""SOC-2 — the student gets EXACTLY 3 real interactions per socratic session.

GOAL: ``docs/goals/GOAL-tres-interacoes.md`` (rubric, immutable during the loop).

Two defects the screenshot exposed (1 message → 0/3 "concluída"):

  (a) OFF-BY-ONE in ``_derive_pacing``: ``should_finalize = used >= MAX-1`` with
      ``used`` ALREADY counting the current turn (the ``+1`` runs before pacing in
      ``socratic_dialogue``). Effect: the session finalizes on the student's 2nd
      real message. Correct: finalize when the current turn is the 3rd
      (``used >= MAX``).

  (b) ZOMBIE SESSION: when ``should_finalize: true`` is served the session is
      never marked ``completed`` in the DB. It stays ``active`` but exhausted; a
      later create-or-get resumes it, the kickoff replays as a real turn
      (transcript no longer empty → GRD4-1), and the 1st student message finalizes
      everything at 0/3.

Each test is a fail-before / pass-after oracle:

  * ``TestThreeRealTurns`` — kickoff honored, real turns 1 & 2 do NOT finalize
    (RED today: turn 2 finalizes), turn 3 DOES; ``interactions_remaining`` is
    2 → 1 → 0 across the three turns.
  * ``TestCompletionEdgeServerSide`` — the finalizing turn flips
    ``chat_sessions.status`` to ``completed`` server-side (RED today: stays
    ``active``), idempotently (no double score edge).
  * ``TestZombieNeverAgain`` — an exhausted ``completed`` session + create-or-get
    yields a NEW virgin session where the kickoff is honored and turn 1 leaves
    ``remaining == MAX-1``.

Headless: in-process FakeSupabaseClient + injected async OpenAI fake, no net/DB.
``asyncio_mode = auto`` (pyproject) lets ``async def test_*`` run unmarked.
"""
from __future__ import annotations

import pytest

from conftest import STUDENT_A_ID, SESSION_A_ID, _user
from fakes import FakeSupabaseClient, FakeAsyncOpenAI
from repositories.chat_repo import ChatRepository
from services.ai_service import AIService, MAX_INTERACTIONS


CONTENT_ID = "content-1"


def _fresh_session_fake() -> FakeSupabaseClient:
    """A brand-new (empty-transcript) ``active`` session for (STUDENT_A, content-1)."""
    return FakeSupabaseClient(
        {
            "chat_sessions": [
                {"id": SESSION_A_ID, "user_id": STUDENT_A_ID, "content_id": CONTENT_ID,
                 "status": "active", "total_messages": 0},
            ],
            "chat_messages": [],
        },
        rpc_enabled=True,
    )


def _svc(response_text: str = "Boa reflexao. O que mais voce nota? "):
    fake = FakeAsyncOpenAI(response_text=response_text)
    return AIService(client=fake, sync_client=None), fake


async def _kickoff(svc, db):
    """Honor the opening trigger on a virgin session (does NOT count)."""
    return await svc.socratic_dialogue(
        student_message="Quero explorar a seguinte questao: o que e lideranca?",
        chapter_content="conteudo",
        initial_question={"text": "O que e lideranca?"},
        session_id=SESSION_A_ID,
        user_id=STUDENT_A_ID,
        db=db,
        is_kickoff=True,
    )


async def _real_turn(svc, db, message: str):
    """A genuine student answer (default is_kickoff=False → counts as a real turn)."""
    return await svc.socratic_dialogue(
        student_message=message,
        chapter_content="conteudo",
        initial_question={"text": "O que e lideranca?"},
        session_id=SESSION_A_ID,
        user_id=STUDENT_A_ID,
        db=db,
    )


# ===========================================================================
# Rubric #1 — 3 real turns, closes on the 3rd (kickoff honored)
# ===========================================================================
class TestThreeRealTurns:
    async def test_full_sequence_kickoff_plus_three_turns(self):
        db = _fresh_session_fake()
        svc, _ = _svc()

        # Kickoff (GRD-4): honored on a virgin session, full limit available.
        k = await _kickoff(svc, db)
        assert k["session_status"]["interactions_remaining"] == MAX_INTERACTIONS
        assert k["session_status"]["should_finalize"] is False
        assert ChatRepository(db).count_user_messages(SESSION_A_ID) == 0

        # Real turn 1 → remaining 2, NOT final.
        t1 = await _real_turn(svc, db, "resposta 1")
        assert t1["session_status"]["interactions_remaining"] == 2
        assert t1["session_status"]["should_finalize"] is False

        # Real turn 2 → remaining 1, NOT final.
        # RED TODAY: used=2 → should_finalize True under `used >= MAX-1` (off-by-one).
        t2 = await _real_turn(svc, db, "resposta 2")
        assert t2["session_status"]["interactions_remaining"] == 1
        assert t2["session_status"]["should_finalize"] is False, (
            "off-by-one: session must NOT finalize on the 2nd real message"
        )

        # Real turn 3 → remaining 0, FINAL (closing synthesis).
        t3 = await _real_turn(svc, db, "resposta 3")
        assert t3["session_status"]["interactions_remaining"] == 0
        assert t3["session_status"]["should_finalize"] is True
        assert t3["response"]["is_final_interaction"] is True

        # Exactly 3 persisted student turns (kickoff never counted).
        assert ChatRepository(db).count_user_messages(SESSION_A_ID) == 3


# ===========================================================================
# Rubric #2 — the finalizing turn marks the session completed server-side
# ===========================================================================
# These exercise the REAL socratic ROUTE handler (``ai_socrates_dialogue``), where
# SOC-2 fix (b) lives: the completion marking is route-level (the diagnosis), so a
# bare service call would not observe it. We drive the real handler with the real
# ``AIService`` (fake OpenAI + fake Supabase) so the whole wiring is under test.
def _route_request(message: str, is_kickoff: bool = False, session_id: str = SESSION_A_ID):
    from routes_ai import SocraticDialogueRequest
    return SocraticDialogueRequest(
        student_message=message,
        chapter_content="conteudo",
        initial_question={"text": "O que e lideranca?"},
        session_id=session_id,
        is_kickoff=is_kickoff,
    )


async def _route_turn(db, message: str, *, is_kickoff: bool = False,
                      session_id: str = SESSION_A_ID, actor: dict | None = None):
    """Invoke the real socratic route handler end-to-end (SOC-2 wiring included)."""
    from routes_ai import ai_socrates_dialogue
    user = actor or _user(STUDENT_A_ID, "STUDENT", "Student A")
    return await ai_socrates_dialogue(
        _route_request(message, is_kickoff=is_kickoff, session_id=session_id),
        current_user=user,
        client=db,
    )


@pytest.fixture
def _route_svc(monkeypatch):
    """Bind ``get_ai_service`` to a real AIService over the fake OpenAI for the route."""
    import routes_ai
    svc = AIService(client=FakeAsyncOpenAI(response_text="Reflexao. E entao? "),
                    sync_client=None)
    monkeypatch.setattr(routes_ai, "get_ai_service", lambda: svc)
    return svc


class TestCompletionEdgeServerSide:
    async def test_finalizing_turn_marks_session_completed(self, _route_svc):
        db = _fresh_session_fake()

        await _route_turn(db, "kick", is_kickoff=True)
        await _route_turn(db, "resposta 1")
        await _route_turn(db, "resposta 2")

        # Not completed until the finalizing turn fires.
        assert db.find("chat_sessions", id=SESSION_A_ID)["status"] == "active"

        t3 = await _route_turn(db, "resposta 3")
        assert t3["session_status"]["should_finalize"] is True

        # RED TODAY: the route never flips the status → still 'active' (zombie).
        assert db.find("chat_sessions", id=SESSION_A_ID)["status"] == "completed", (
            "the finalizing turn must mark the session completed server-side"
        )

    async def test_completion_edge_is_idempotent_no_double_score(self, _route_svc, monkeypatch):
        """Re-serving a finalize-shaped turn must not re-run the completion edge.

        The DATA-GAM-3 score (``compute_performance_score``) is computed ONLY on the
        first active→completed transition. A spy on that function is the unambiguous
        proxy for "the completion edge ran" (the fake records post-write row
        snapshots, so filtering the mutation log on the persisted ``status`` /
        ``performance_score`` value is polluted by later ``total_messages`` bumps)."""
        import routes_ai
        calls = {"n": 0}
        real_score = routes_ai.compute_performance_score

        def _spy(turns):
            calls["n"] += 1
            return real_score(turns)

        monkeypatch.setattr(routes_ai, "compute_performance_score", _spy)

        db = _fresh_session_fake()
        await _route_turn(db, "kick", is_kickoff=True)
        await _route_turn(db, "resposta 1")
        await _route_turn(db, "resposta 2")
        await _route_turn(db, "resposta 3")  # first finalize → completed once

        assert calls["n"] == 1, "completion edge (score) must run exactly once on finalize"
        assert db.find("chat_sessions", id=SESSION_A_ID)["status"] == "completed"

        # A subsequent finalize-shaped call on the already-completed session must be
        # a no-op for the completion edge (idempotent short-circuit BEFORE the score
        # recomputes) — the spy count stays at 1.
        await _route_turn(db, "resposta extra")
        assert calls["n"] == 1, (
            "completion edge must be idempotent — score must not recompute on re-complete"
        )


# ===========================================================================
# Rubric #3 — zombie never again: completed session → fresh virgin session
# ===========================================================================
class TestZombieNeverAgain:
    async def test_exhausted_completed_session_yields_fresh_virgin_session(self):
        """An exhausted ``completed`` session must NOT be resumed; create-or-get
        makes a NEW virgin session where the kickoff is honored and the student has
        the full 3 interactions again. Mirrors SEC-CHAT-3 + GRD-3 at the route."""
        # Seed a completed, exhausted session for the pair (the zombie's would-be
        # successor state after the fix marks it completed).
        db = FakeSupabaseClient(
            {
                "chat_sessions": [
                    {"id": SESSION_A_ID, "user_id": STUDENT_A_ID, "content_id": CONTENT_ID,
                     "status": "completed", "total_messages": 8,
                     "created_at": "2026-07-15T10:00:00Z"},
                ],
                "chat_messages": [
                    {"id": "old-1", "session_id": SESSION_A_ID, "role": "user",
                     "content": "old", "created_at": "2026-07-15T10:01:00Z"},
                ],
            },
            rpc_enabled=True,
        )

        # Emulate the create-or-get route decision (SEC-CHAT-3): a completed session
        # is never reactivated — a NEW distinct session row is created.
        from routes_ai import _create_chat_session_row
        new_row = _create_chat_session_row(db, STUDENT_A_ID, CONTENT_ID, "O que e lideranca?")
        assert new_row["id"] != SESSION_A_ID, "must be a NEW session, not the zombie"
        assert new_row["status"] == "active"

        # The new session is virgin (empty transcript) → kickoff is honored on it.
        new_id = new_row["id"]
        svc, _ = _svc()
        k = await svc.socratic_dialogue(
            student_message="Quero explorar a seguinte questao: o que e lideranca?",
            chapter_content="conteudo",
            initial_question={"text": "O que e lideranca?"},
            session_id=new_id,
            user_id=STUDENT_A_ID,
            db=db,
            is_kickoff=True,
        )
        assert k["session_status"]["interactions_remaining"] == MAX_INTERACTIONS
        assert k["session_status"]["should_finalize"] is False
        assert ChatRepository(db).count_user_messages(new_id) == 0

        # Real turn 1 on the fresh session → remaining = MAX-1 (2).
        t1 = await svc.socratic_dialogue(
            student_message="minha primeira resposta real",
            chapter_content="conteudo",
            initial_question={"text": "O que e lideranca?"},
            session_id=new_id,
            user_id=STUDENT_A_ID,
            db=db,
        )
        assert t1["session_status"]["interactions_remaining"] == MAX_INTERACTIONS - 1
        assert t1["session_status"]["should_finalize"] is False
