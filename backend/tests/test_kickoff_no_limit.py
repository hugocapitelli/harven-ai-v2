"""GRD-4 — the socratic kickoff must NOT consume the student's interaction limit.

Symptom (Hugo, live): starting a session → tutor kickoff arrives → limit already
exhausted (0/3, "Sessão concluída", input blocked) with ZERO student messages.

Root cause (Frente B): the kickoff is the tutor's opening TRIGGER — the frontend
sends a synthetic "Quero explorar a questão ..." string only so the model produces
the first question. The backend persisted it as a ``role='user'`` turn and counted
it, so a brand-new session read ``used=1`` → ``remaining=2`` (one interaction lost);
combined with the it2/it3 stale-session resolution bug (uncommitted on Hugo's
backend), a stale completed session made it read ``used>=MAX`` → 0/3 finalized.

Fix: ``socratic_dialogue(is_kickoff=True)`` skips persisting the trigger as a user
turn, so pacing starts at ``used=0`` (remaining = MAX, not finalized). The assistant
reply still persists (opening question kept in the transcript). Real student turns
(``is_kickoff`` default False) are unchanged.

RED-first: written to fail before the fix (kickoff counted → remaining 2 / a user
turn persisted), pass after. Runs headless on the fake OpenAI + fake Supabase.
"""
from __future__ import annotations

import pytest

from conftest import STUDENT_A_ID, SESSION_A_ID
from fakes import FakeSupabaseClient, FakeAsyncOpenAI
from repositories.chat_repo import ChatRepository
from services.ai_service import AIService, MAX_INTERACTIONS

pytestmark = pytest.mark.asyncio


def _fresh_session_fake() -> FakeSupabaseClient:
    return FakeSupabaseClient(
        {
            "chat_sessions": [
                {"id": SESSION_A_ID, "user_id": STUDENT_A_ID, "content_id": "content-1",
                 "status": "active", "total_messages": 0},
            ],
            "chat_messages": [],
        },
        rpc_enabled=True,
    )


def _svc(response_text: str = "Bem-vindo! O que você já sabe sobre isso? "):
    fake = FakeAsyncOpenAI(response_text=response_text)
    return AIService(client=fake, sync_client=None), fake


class TestKickoffDoesNotConsumeLimit:
    async def test_kickoff_leaves_full_limit_and_does_not_finalize(self):
        db = _fresh_session_fake()
        svc, _ = _svc()
        out = await svc.socratic_dialogue(
            student_message="Quero explorar a seguinte questão: o que é liderança?",
            chapter_content="conteudo",
            initial_question={"text": "O que é liderança?"},
            session_id=SESSION_A_ID,
            user_id=STUDENT_A_ID,
            db=db,
            is_kickoff=True,
        )
        # Fresh session + kickoff → the FULL limit is available, session NOT finalized.
        assert out["session_status"]["interactions_remaining"] == MAX_INTERACTIONS
        assert out["session_status"]["should_finalize"] is False

    async def test_kickoff_persists_only_the_assistant_turn(self):
        db = _fresh_session_fake()
        svc, _ = _svc()
        await svc.socratic_dialogue(
            student_message="Quero explorar a seguinte questão: X?",
            chapter_content="c",
            initial_question={"text": "X?"},
            session_id=SESSION_A_ID,
            user_id=STUDENT_A_ID,
            db=db,
            is_kickoff=True,
        )
        roles = sorted(m["role"] for m in db.rows("chat_messages"))
        # Only the tutor's opening question is persisted — the trigger is NOT a
        # student turn, so ``count_user_messages`` stays 0.
        assert roles == ["assistant"]
        assert ChatRepository(db).count_user_messages(SESSION_A_ID) == 0

    async def test_first_real_answer_after_kickoff_counts_one(self):
        db = _fresh_session_fake()
        svc, _ = _svc()
        # Kickoff (not counted).
        await svc.socratic_dialogue(
            student_message="Quero explorar a seguinte questão: X?",
            chapter_content="c", initial_question={"text": "X?"},
            session_id=SESSION_A_ID, user_id=STUDENT_A_ID, db=db, is_kickoff=True,
        )
        # First genuine student answer (default is_kickoff=False) → counts as 1.
        out = await svc.socratic_dialogue(
            student_message="Acho que liderança é influência.",
            chapter_content="c", initial_question={"text": "X?"},
            session_id=SESSION_A_ID, user_id=STUDENT_A_ID, db=db,
        )
        assert ChatRepository(db).count_user_messages(SESSION_A_ID) == 1
        assert out["session_status"]["interactions_remaining"] == MAX_INTERACTIONS - 1
        assert out["session_status"]["should_finalize"] is False

    async def test_real_turn_default_still_counts_regression(self):
        """Regression: without is_kickoff, a message is a real student turn (counted),
        preserving the pre-GRD-4 contract for every existing caller."""
        db = _fresh_session_fake()
        svc, _ = _svc()
        await svc.socratic_dialogue(
            student_message="minha resposta real",
            chapter_content="c", initial_question={"text": "Q?"},
            session_id=SESSION_A_ID, user_id=STUDENT_A_ID, db=db,
        )
        assert ChatRepository(db).count_user_messages(SESSION_A_ID) == 1
        roles = sorted(m["role"] for m in db.rows("chat_messages"))
        assert roles == ["assistant", "user"]


class TestKickoffAbuseGuard:
    """GRD4-1 [ALTA]: ``is_kickoff`` is client-controlled. Without a server-side
    guard, a student calling the API directly with ``is_kickoff=True`` on EVERY
    message would (a) chat unlimited (``remaining`` never decrements) and (b) have
    NONE of their answers persisted — evading the teacher's transcript and grade.

    Guard: ``is_kickoff`` is honored ONLY when the session has zero student turns
    (``count_user_messages == 0``). From the 2nd message on, it is treated as a real
    turn: persisted and counted."""

    async def test_repeated_is_kickoff_only_honored_on_empty_session(self):
        db = _fresh_session_fake()
        svc, _ = _svc()

        # 1st call: genuine kickoff on an empty session → not counted.
        out1 = await svc.socratic_dialogue(
            student_message="Quero explorar a seguinte questão: X?",
            chapter_content="c", initial_question={"text": "X?"},
            session_id=SESSION_A_ID, user_id=STUDENT_A_ID, db=db, is_kickoff=True,
        )
        assert out1["session_status"]["interactions_remaining"] == MAX_INTERACTIONS
        assert ChatRepository(db).count_user_messages(SESSION_A_ID) == 0

        # Attacker replays is_kickoff=True on substantive answers. Each of these must
        # now be treated as a REAL turn (session no longer empty): persisted + counted.
        for i in range(1, MAX_INTERACTIONS + 2):  # go past the limit
            out = await svc.socratic_dialogue(
                student_message=f"Resposta substantiva número {i} tentando burlar o limite.",
                chapter_content="c", initial_question={"text": "X?"},
                session_id=SESSION_A_ID, user_id=STUDENT_A_ID, db=db,
                is_kickoff=True,  # abusive flag — must be IGNORED after the first turn
            )
            # count keeps growing (answers ARE persisted — no history evasion)
            assert ChatRepository(db).count_user_messages(SESSION_A_ID) == i
            # remaining clamps at 0 (never negative) as real turns accumulate
            assert out["session_status"]["interactions_remaining"] == max(0, MAX_INTERACTIONS - i)

        # After MAX real turns the session is finalized despite the abusive flag.
        final = await svc.socratic_dialogue(
            student_message="mais uma tentativa de burlar",
            chapter_content="c", initial_question={"text": "X?"},
            session_id=SESSION_A_ID, user_id=STUDENT_A_ID, db=db, is_kickoff=True,
        )
        assert final["session_status"]["should_finalize"] is True

    async def test_abuse_persists_every_answer_no_history_evasion(self):
        db = _fresh_session_fake()
        svc, _ = _svc()
        # kickoff (not counted)
        await svc.socratic_dialogue(
            student_message="Quero explorar a seguinte questão: X?",
            chapter_content="c", initial_question={"text": "X?"},
            session_id=SESSION_A_ID, user_id=STUDENT_A_ID, db=db, is_kickoff=True,
        )
        # 3 abusive is_kickoff answers → all 3 persist as user turns (teacher sees them).
        for i in range(3):
            await svc.socratic_dialogue(
                student_message=f"resposta {i}",
                chapter_content="c", initial_question={"text": "X?"},
                session_id=SESSION_A_ID, user_id=STUDENT_A_ID, db=db, is_kickoff=True,
            )
        user_msgs = [m for m in db.rows("chat_messages") if m["role"] == "user"]
        assert len(user_msgs) == 3, "abusive is_kickoff must NOT let answers evade the transcript"
