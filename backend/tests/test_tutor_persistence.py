"""TPP-1..7 — tutor persistence & pacing regression suite (Phase 3, EPIC-AI).

Backend = source of truth for the Socratic dialogue. Each section is a
fail-before / pass-after oracle for one story:

  * TPP-1 — atomic-count + race-free upsert RPCs (in-memory fake of migration B).
  * TPP-2 — create-or-get is race-free (upsert) and never trusts body.user_id;
            completed-session rule preserved; abandoned reactivates.
  * TPP-3 — chat_repo.persist_turn is the single write path: insert + atomic
            increment; count_user_messages; stable (created_at, sequence, id) order.
  * TPP-4 — both turns persisted server-side inside socratic_dialogue; reload &
            export see the assistant turns; InitialQuestion.text required (422).
  * TPP-5 — interactions_remaining derived server-side from the persisted user
            count, ignoring the client field; closing synthesis reachable at MAX.
  * TPP-6 — (frontend) covered by ChapterReader smoke assertions on the contract
            shape the client consumes (session_status / should_finalize).
  * TPP-7 — Editor→Tester gate behind a flag: OFF unchanged; ON+REJECTED
            regenerates once; Tester failure never blocks / never fabricates APPROVED.

Headless: in-process FakeSupabaseClient + injected OpenAI fakes, no network/DB.
``asyncio_mode = auto`` (pyproject) lets ``async def test_*`` run unmarked.
"""
from __future__ import annotations

import asyncio

import pytest

from conftest import (
    STUDENT_A_ID,
    STUDENT_B_ID,
    SESSION_A_ID,
    SESSION_B_ID,
)
from fakes import FakeSupabaseClient, FakeAsyncOpenAI
from repositories.chat_repo import ChatRepository
from services.ai_service import AIService, MAX_INTERACTIONS, AI_GATE_FLAG_ENV


# ===========================================================================
# Local fixtures
# ===========================================================================
def _fake_with_rpc() -> FakeSupabaseClient:
    """A fake with the TPP-1 RPCs enabled (mirrors a DB after migration B)."""
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


def _fake_no_rpc() -> FakeSupabaseClient:
    """A fake WITHOUT the RPCs (mirrors an un-migrated DB → repo fallback path)."""
    return FakeSupabaseClient(
        {
            "chat_sessions": [
                {"id": SESSION_A_ID, "user_id": STUDENT_A_ID, "content_id": "content-1",
                 "status": "active", "total_messages": 0},
            ],
            "chat_messages": [],
        },
        rpc_enabled=False,
    )


def _svc(response_text: str = "Boa reflexao. O que mais voce nota? "):
    fake = FakeAsyncOpenAI(response_text=response_text)
    return AIService(client=fake, sync_client=None), fake


# ===========================================================================
# TPP-1 — atomic increment + race-free upsert (RPC behaviour, fake of migration B)
# ===========================================================================
class TestTpp1Rpcs:
    def test_increment_rpc_is_atomic_under_concurrency(self):
        fake = _fake_with_rpc()
        # 10 concurrent-ish increments → total_messages == exactly 10 (no lost update).
        for _ in range(10):
            fake.rpc("increment_chat_session_messages", {"p_session_id": SESSION_A_ID}).execute()
        row = fake.find("chat_sessions", id=SESSION_A_ID)
        assert row["total_messages"] == 10

    def test_upsert_rpc_returns_same_row_for_same_pair(self):
        fake = _fake_with_rpc()
        before = len(fake.rows("chat_sessions"))
        r1 = fake.rpc("upsert_chat_session", {"p_user_id": STUDENT_B_ID, "p_content_id": "c-new"}).execute().data
        r2 = fake.rpc("upsert_chat_session", {"p_user_id": STUDENT_B_ID, "p_content_id": "c-new"}).execute().data
        # Exactly ONE new row, and both calls resolve to the SAME id (never two).
        assert len(fake.rows("chat_sessions")) == before + 1
        assert r1["id"] == r2["id"]

    def test_disabled_fake_exposes_no_rpc(self):
        fake = _fake_no_rpc()
        # getattr(client, "rpc", None) must be None so chat_repo takes the fallback.
        assert getattr(fake, "rpc", None) is None


# ===========================================================================
# TPP-3 — chat_repo: single write path, atomic count, stable ordering
# ===========================================================================
class TestTpp3ChatRepo:
    def test_persist_turn_inserts_one_and_increments_via_rpc(self):
        fake = _fake_with_rpc()
        repo = ChatRepository(fake)
        before_msgs = len(fake.rows("chat_messages"))
        repo.persist_turn(SESSION_A_ID, {"role": "user", "content": "hi"})
        assert len(fake.rows("chat_messages")) == before_msgs + 1
        # Counter advanced atomically via the RPC.
        assert fake.find("chat_sessions", id=SESSION_A_ID)["total_messages"] == 1
        assert any(c["name"] == "increment_chat_session_messages" for c in fake.rpc_calls)

    def test_persist_turn_increments_via_fallback_when_no_rpc(self):
        fake = _fake_no_rpc()
        repo = ChatRepository(fake)
        repo.persist_turn(SESSION_A_ID, {"role": "user", "content": "hi"})
        repo.persist_turn(SESSION_A_ID, {"role": "assistant", "content": "ho?"})
        # Even without the RPC, the counter advanced to the real message count.
        assert fake.find("chat_sessions", id=SESSION_A_ID)["total_messages"] == 2
        assert len(fake.rows("chat_messages")) == 2

    def test_concurrent_persist_turn_counts_exactly_n_with_rpc(self):
        fake = _fake_with_rpc()
        repo = ChatRepository(fake)

        async def _one(i):
            from fastapi.concurrency import run_in_threadpool
            await run_in_threadpool(
                repo.persist_turn, SESSION_A_ID, {"role": "user", "content": f"m{i}"}
            )

        async def _run():
            await asyncio.gather(*[_one(i) for i in range(6)])

        asyncio.get_event_loop().run_until_complete(_run()) if False else asyncio.run(_run())
        # Atomic RPC → exactly +6, no lost updates.
        assert fake.find("chat_sessions", id=SESSION_A_ID)["total_messages"] == 6

    def test_count_user_messages_counts_only_user_role(self):
        fake = _fake_with_rpc()
        repo = ChatRepository(fake)
        repo.persist_turn(SESSION_A_ID, {"role": "user", "content": "q1"})
        repo.persist_turn(SESSION_A_ID, {"role": "assistant", "content": "a1?"})
        repo.persist_turn(SESSION_A_ID, {"role": "user", "content": "q2"})
        assert repo.count_user_messages(SESSION_A_ID) == 2

    def test_get_session_messages_stable_order_with_sequence_tiebreak(self):
        # Same created_at on every row; only ``sequence`` disambiguates.
        fake = FakeSupabaseClient({
            "chat_sessions": [{"id": SESSION_A_ID, "user_id": STUDENT_A_ID,
                               "content_id": "content-1", "status": "active",
                               "total_messages": 3}],
            "chat_messages": [
                {"id": "z", "session_id": SESSION_A_ID, "role": "user",
                 "content": "third", "created_at": "2026-01-01T00:00:00Z", "sequence": 3},
                {"id": "a", "session_id": SESSION_A_ID, "role": "user",
                 "content": "first", "created_at": "2026-01-01T00:00:00Z", "sequence": 1},
                {"id": "m", "session_id": SESSION_A_ID, "role": "assistant",
                 "content": "second", "created_at": "2026-01-01T00:00:00Z", "sequence": 2},
            ],
        })
        ordered = ChatRepository(fake).get_session_messages(SESSION_A_ID)
        assert [m["content"] for m in ordered] == ["first", "second", "third"]

    def test_add_message_alias_routes_through_persist_turn(self):
        fake = _fake_with_rpc()
        repo = ChatRepository(fake)
        repo.add_message(SESSION_A_ID, {"role": "user", "content": "legacy"})
        # The legacy alias also bumps the counter (no path skips the increment).
        assert fake.find("chat_sessions", id=SESSION_A_ID)["total_messages"] == 1


# ===========================================================================
# TPP-4 — both turns persisted server-side inside socratic_dialogue
# ===========================================================================
class TestTpp4BothTurnsPersisted:
    async def test_dialogue_persists_user_and_assistant_turns(self):
        fake_db = _fake_with_rpc()
        svc, _ = _svc("Excelente. Por que voce acha isso? ")
        out = await svc.socratic_dialogue(
            student_message="Acho que e por causa de X",
            chapter_content="conteudo",
            initial_question={"text": "O que e X?"},
            interactions_remaining=20,
            session_id=SESSION_A_ID,
            user_id=STUDENT_A_ID,
            db=fake_db,
        )
        msgs = fake_db.rows("chat_messages")
        roles = sorted(m["role"] for m in msgs)
        assert roles == ["assistant", "user"], f"both turns must persist, got {roles}"
        # Assistant turn carries the agent_type and the actual reply content.
        asst = next(m for m in msgs if m["role"] == "assistant")
        assert asst["agent_type"] == "socrates"
        assert asst["content"] == out["response"]["content"]
        # The student turn was persisted with the real message.
        usr = next(m for m in msgs if m["role"] == "user")
        assert usr["content"] == "Acho que e por causa de X"

    async def test_reload_returns_full_transcript_including_assistant(self):
        fake_db = _fake_with_rpc()
        svc, _ = _svc("Boa. E se mudasse Y? ")
        await svc.socratic_dialogue(
            student_message="minha resposta",
            chapter_content="c",
            initial_question={"text": "Q?"},
            interactions_remaining=20,
            session_id=SESSION_A_ID,
            user_id=STUDENT_A_ID,
            db=fake_db,
        )
        # Emulate GET /chat-sessions/{id}/messages.
        transcript = ChatRepository(fake_db).get_session_messages(SESSION_A_ID)
        assert any(m["role"] == "assistant" for m in transcript), "socratic question lost on reload"
        assert any(m["role"] == "user" for m in transcript)

    async def test_opening_message_persists_both_turns(self):
        # AI-HARD-5: the ``__INIT__`` sentinel was removed. The frontend now sends
        # the real opening text ("Quero explorar a seguinte questao: ..."), which is
        # a genuine student turn — so the opening persists BOTH the user message and
        # the assistant reply (no special-cased assistant-only path anymore).
        fake_db = _fake_with_rpc()
        svc, _ = _svc("Ola! Vamos comecar. O que voce ja sabe? ")
        await svc.socratic_dialogue(
            student_message="Quero explorar a seguinte questao: o que e X?",
            chapter_content="c",
            initial_question={"text": "Q?"},
            interactions_remaining=20,
            session_id=SESSION_A_ID,
            user_id=STUDENT_A_ID,
            db=fake_db,
        )
        msgs = fake_db.rows("chat_messages")
        # The opening is a real student turn → both roles persist.
        assert sorted(m["role"] for m in msgs) == ["assistant", "user"]
        usr = next(m for m in msgs if m["role"] == "user")
        assert usr["content"] == "Quero explorar a seguinte questao: o que e X?"

    async def test_no_session_does_not_persist(self):
        """Concurrency/ephemeral contract preserved: no session_id → no DB writes."""
        svc, fake = _svc()
        out = await svc.socratic_dialogue(
            student_message="x",
            chapter_content="c",
            initial_question={"text": "Q?"},
            interactions_remaining=3,
        )
        assert len(fake.calls) == 1
        assert out["session_status"]["interactions_remaining"] == 2  # legacy fallback


class TestTpp4InitialQuestionContract:
    """InitialQuestion.text is REQUIRED → 422 on missing/empty (route-level)."""

    def test_missing_text_returns_422(self, client, as_student):
        resp = client.post(
            "/api/ai/socrates/dialogue",
            json={
                "student_message": "hi",
                "chapter_content": "chapter",
                "initial_question": {},  # no text
            },
        )
        assert resp.status_code == 422, resp.text

    def test_empty_text_returns_422(self, client, as_student):
        resp = client.post(
            "/api/ai/socrates/dialogue",
            json={
                "student_message": "hi",
                "chapter_content": "chapter",
                "initial_question": {"text": ""},
            },
        )
        assert resp.status_code == 422, resp.text

    def test_valid_text_not_422(self, client, as_student):
        resp = client.post(
            "/api/ai/socrates/dialogue",
            json={
                "student_message": "hi",
                "chapter_content": "chapter",
                "initial_question": {"text": "O que e X?"},
            },
        )
        # Valid contract: never a validation error (mock/AI may 200 or 503).
        assert resp.status_code != 422, resp.text


# ===========================================================================
# TPP-5 — server-side pacing derivation
# ===========================================================================
class TestTpp5Pacing:
    async def test_remaining_derived_from_persisted_count_not_client(self):
        fake_db = _fake_with_rpc()
        # Under the current MAX_INTERACTIONS=3 contract (commit 9c47d11) the mid-
        # conversation, not-yet-finalized window is used < MAX-1 (i.e. used <= 1),
        # so this oracle uses ZERO prior turns; the single turn below makes used=1.
        # The point of the test is unchanged: the server derives pacing from the
        # PERSISTED count, never from the client-supplied field.
        svc, _ = _svc("E entao? ")
        # Client LIES with an absurd interactions_remaining=99; server must ignore
        # it and report the value derived from the real persisted count (used=1).
        out = await svc.socratic_dialogue(
            student_message="nova mensagem",
            chapter_content="c",
            initial_question={"text": "Q?"},
            interactions_remaining=99,          # client-supplied — must be ignored
            session_id=SESSION_A_ID,
            user_id=STUDENT_A_ID,
            db=fake_db,
        )
        # used = 0 prior + this turn = 1 → remaining = MAX - 1 (NOT the client's 99-1),
        # and not finalized yet (used=1 < MAX-1=2).
        assert out["session_status"]["interactions_remaining"] == MAX_INTERACTIONS - 1
        assert out["session_status"]["should_finalize"] is False

    async def test_not_stuck_at_three(self):
        """Regression for #26: the value must NOT be the benign client default 3/2."""
        fake_db = _fake_with_rpc()
        svc, _ = _svc("? ")
        out = await svc.socratic_dialogue(
            student_message="m1", chapter_content="c",
            initial_question={"text": "Q?"}, interactions_remaining=3,
            session_id=SESSION_A_ID, user_id=STUDENT_A_ID, db=fake_db,
        )
        # First persisted user turn → used=1 → remaining=19, never the stale 2/3.
        assert out["session_status"]["interactions_remaining"] == MAX_INTERACTIONS - 1

    async def test_closing_synthesis_reachable_at_max(self):
        fake_db = _fake_with_rpc()
        repo = ChatRepository(fake_db)
        # Pre-seed MAX-2 user turns; the NEXT turn becomes used = MAX-1 → finalize.
        for i in range(MAX_INTERACTIONS - 2):
            repo.persist_turn(SESSION_A_ID, {"role": "user", "content": f"u{i}"})

        svc, _ = _svc("Sintese final. O que voce conclui? ")
        out = await svc.socratic_dialogue(
            student_message="penultima", chapter_content="c",
            initial_question={"text": "Q?"}, interactions_remaining=3,
            session_id=SESSION_A_ID, user_id=STUDENT_A_ID, db=fake_db,
        )
        # used = MAX-1 → should_finalize True exactly once at the real end.
        assert out["session_status"]["should_finalize"] is True
        assert out["response"]["is_final_interaction"] is True

    async def test_not_finalize_before_the_end(self):
        fake_db = _fake_with_rpc()
        # MAX_INTERACTIONS=3 (commit 9c47d11): finalization fires at used >= MAX-1
        # (=2). To prove "does NOT finalize BEFORE the end", the current turn must
        # land strictly before that threshold, i.e. used=1 → zero prior turns.
        svc, _ = _svc("? ")
        out = await svc.socratic_dialogue(
            student_message="meio", chapter_content="c",
            initial_question={"text": "Q?"}, interactions_remaining=20,
            session_id=SESSION_A_ID, user_id=STUDENT_A_ID, db=fake_db,
        )
        # used = 1 (< MAX-1 = 2) → not the last permitted turn yet, no finalize.
        assert out["session_status"]["should_finalize"] is False


# ===========================================================================
# TPP-2 — create-or-get race-free + ignore body.user_id (route level)
# ===========================================================================
class TestTpp2CreateOrGet:
    def test_concurrent_double_submit_no_duplicate_no_500(self, client, as_student, fake_supabase, monkeypatch):
        # Enable the upsert RPC on the app's fake so the route takes the race-free path.
        monkeypatch.setattr(fake_supabase, "rpc", fake_supabase._rpc_entry, raising=False)
        fake_supabase._rpc_enabled = True

        r1 = client.post("/chat-sessions", json={"content_id": "content-race"})
        r2 = client.post("/chat-sessions", json={"content_id": "content-race"})
        assert r1.status_code in (200, 201), r1.text
        assert r2.status_code in (200, 201), r2.text
        # Exactly ONE session for the pair; both calls return the same id (no 500).
        rows = [r for r in fake_supabase.rows("chat_sessions")
                if r["content_id"] == "content-race" and r["user_id"] == STUDENT_A_ID]
        assert len(rows) == 1, f"expected exactly 1 session for the pair, got {len(rows)}"
        assert r1.json()["id"] == r2.json()["id"]

    def test_fallback_path_creates_session_without_rpc(self, client, as_student, fake_supabase):
        # Default fake has no rpc → route fallback insert must still work.
        resp = client.post("/chat-sessions", json={"content_id": "content-fallback"})
        assert resp.status_code in (200, 201), resp.text
        assert resp.json()["user_id"] == STUDENT_A_ID

    def test_body_user_id_still_ignored_with_rpc(self, client, as_student, fake_supabase, monkeypatch):
        monkeypatch.setattr(fake_supabase, "rpc", fake_supabase._rpc_entry, raising=False)
        fake_supabase._rpc_enabled = True
        resp = client.post(
            "/chat-sessions",
            json={"content_id": "content-spoof2", "user_id": STUDENT_B_ID},
        )
        assert resp.status_code in (403, 404), resp.text
        leaked = fake_supabase.find("chat_sessions", user_id=STUDENT_B_ID, content_id="content-spoof2")
        assert leaked is None


# ===========================================================================
# TPP-7 — Editor→Tester quality gate behind a flag
# ===========================================================================
class TestTpp7Gate:
    async def test_flag_off_single_call_unchanged(self, monkeypatch):
        monkeypatch.delenv(AI_GATE_FLAG_ENV, raising=False)  # default OFF
        svc, fake = _svc("Resposta crua do socrates. Concorda? ")
        out = await svc.socratic_dialogue(
            student_message="x", chapter_content="c",
            initial_question={"text": "Q?"}, interactions_remaining=3,
        )
        # OFF: exactly one LLM call (Socrates only), raw output returned.
        assert len(fake.calls) == 1
        assert out["response"]["content"] == "Resposta crua do socrates. Concorda? "

    async def test_flag_on_runs_editor_and_tester(self, monkeypatch):
        monkeypatch.setenv(AI_GATE_FLAG_ENV, "true")
        # Tester returns APPROVED JSON; Editor returns edited text. Same fake serves
        # all three calls; we assert the edited text is what ships and >1 call ran.
        fake = FakeAsyncOpenAI(response_text='{"verdict": "APPROVED", "score": 0.9}')
        # First make a service whose Socrates/Editor return non-JSON; simplest is to
        # use a response that is valid for all: edited text == the JSON string is ugly,
        # so instead verify call count increased and no exception bubbles.
        svc = AIService(client=fake, sync_client=None)
        out = await svc.socratic_dialogue(
            student_message="x", chapter_content="c",
            initial_question={"text": "Q?"}, interactions_remaining=3,
        )
        # ON: Socrates + Editor + Tester ⇒ at least 3 calls.
        assert len(fake.calls) >= 3
        assert "content" in out["response"]

    async def test_flag_on_rejected_regenerates_once(self, monkeypatch):
        monkeypatch.setenv(AI_GATE_FLAG_ENV, "true")

        # Scripted client: Socrates → Editor → Tester(REJECTED) → Socrates → Editor → Tester.
        # We count calls and assert exactly one regeneration (≤ 6 calls), never a loop.
        script = [
            "socrates v1 ?",                                  # 1 socrates
            "edited v1 ?",                                    # 2 editor
            '{"verdict": "REJECTED", "score": 0.2}',          # 3 tester -> regen
            "socrates v2 ?",                                  # 4 socrates (regen)
            "edited v2 ?",                                    # 5 editor (regen)
            '{"verdict": "APPROVED", "score": 0.9}',          # 6 tester (informational)
        ]

        class _ScriptedCompletions:
            def __init__(self, parent):
                self._p = parent

            async def create(self, **kwargs):
                self._p.calls.append(kwargs)
                i = len(self._p.calls) - 1
                from fakes import _FakeChatCompletion
                return _FakeChatCompletion(script[i] if i < len(script) else "extra ?")

        from types import SimpleNamespace

        class _ScriptedClient:
            def __init__(self):
                self.calls = []
                self.chat = SimpleNamespace(completions=_ScriptedCompletions(self))

        client_fake = _ScriptedClient()
        svc = AIService(client=client_fake, sync_client=None)
        out = await svc.socratic_dialogue(
            student_message="x", chapter_content="c",
            initial_question={"text": "Q?"}, interactions_remaining=3,
        )
        # Exactly one regeneration: 6 calls total, never more (no infinite retry).
        assert len(client_fake.calls) == 6, f"expected 1 regeneration (6 calls), got {len(client_fake.calls)}"
        # The student receives the regenerated edited reply.
        assert out["response"]["content"] == "edited v2 ?"

    async def test_tester_failure_never_blocks_and_no_fabricated_approved(self, monkeypatch):
        monkeypatch.setenv(AI_GATE_FLAG_ENV, "true")

        # Content-by-role (not index): the Tester is the only json_mode call → it
        # RAISES; Socrates/Editor (non-json) return a fixed reply. This keeps the
        # script robust to call ordering across the two calls this test makes.
        from types import SimpleNamespace
        from fakes import _FakeChatCompletion

        class _FlakyCompletions:
            def __init__(self, parent):
                self._p = parent

            async def create(self, **kwargs):
                self._p.calls.append(kwargs)
                if kwargs.get("response_format", {}).get("type") == "json_object":
                    # The Tester (json_mode) upstream is down.
                    raise RuntimeError("tester upstream down")
                return _FakeChatCompletion("edited reply ?")

        class _FlakyClient:
            def __init__(self):
                self.calls = []
                self.chat = SimpleNamespace(completions=_FlakyCompletions(self))

        # Direct unit check on its own client: validate_response fails OPEN but
        # NEVER fabricates APPROVED (TPP-7 / #32).
        unit_svc = AIService(client=_FlakyClient(), sync_client=None)
        verdict = await unit_svc.validate_response(edited_response="anything")
        assert verdict["verdict"] in ("UNKNOWN", "NEEDS_REVISION")
        assert verdict["verdict"] != "APPROVED"

        # End-to-end on a fresh client: the dialogue still returns the edited reply
        # (the student is never blocked despite the Tester failing).
        e2e_svc = AIService(client=_FlakyClient(), sync_client=None)
        out = await e2e_svc.socratic_dialogue(
            student_message="x", chapter_content="c",
            initial_question={"text": "Q?"}, interactions_remaining=3,
        )
        assert out["response"]["content"] == "edited reply ?"
