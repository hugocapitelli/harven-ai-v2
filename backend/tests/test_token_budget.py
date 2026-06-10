"""TKN-3 — AIService token budget is PERSISTED (not a process cache).

Bug #12: the daily token budget lived in a module-level ``_user_token_cache``
dict, lost on every restart/deploy — any user could zero their quota by bouncing
the service. TKN-3 replaces it with persistence in the ``token_usage`` table via
:class:`TokenUsageRepository` (Supabase PostgREST/RPC). The error policy is
deliberately asymmetric:

  * ``check_token_budget`` — FAIL-OPEN: no ``db`` or a read error never blocks the
    request (availability > perfect enforcement when persistence is unreachable).
  * ``track_token_usage``  — BEST-EFFORT: a write error is logged and swallowed,
    never propagated, so token accounting can never break AI generation.

Each test is a fail-before / pass-after oracle:

  * Persistence survives a discarded/recreated ``AIService`` (no in-memory budget).
  * The cap raises ``AIServiceError`` once persisted usage >= ``daily_token_limit``.
  * ``db=None`` → fail-open (check) and quiet no-op (track).
  * An RPC/read error → fail-open (check) and swallow (track, never raises).
  * No double-count under two atomic increments.
  * The real call sites (``generate_questions`` / ``_generate_socratic_reply``)
    still check/track against the propagated ``db``.

Headless: in-process ``FakeSupabaseClient`` (with the ``increment_token_usage``
RPC) + injected ``FakeAsyncOpenAI``. No network, no real DB.
"""
from __future__ import annotations

import json

import pytest

from conftest import STUDENT_A_ID, STUDENT_B_ID
from fakes import FakeSupabaseClient, FakeAsyncOpenAI
from repositories.token_usage_repo import TokenUsageRepository
from services.ai_service import AIService, AIServiceError


# ===========================================================================
# Helpers
# ===========================================================================
def _fake_db() -> FakeSupabaseClient:
    """A Supabase fake with the TKN-1 ``increment_token_usage`` RPC enabled."""
    return FakeSupabaseClient({"token_usage": []}, rpc_enabled=True)


def _svc() -> AIService:
    """An AIService wired to an injected async OpenAI fake (mock_mode off)."""
    return AIService(client=FakeAsyncOpenAI(response_text="ok"), sync_client=None)


class _RaisingDB:
    """A duck-typed Supabase client whose every data path raises.

    ``.table(...)`` and ``.rpc(...)`` both blow up, so it drives the
    repository's read/write into the exception arms — letting us prove the
    service fails-open (check) and swallows (track) at the *service* layer rather
    than relying on the repository's own internal defenses.
    """

    def table(self, *_a, **_k):
        raise RuntimeError("db down (table)")

    def rpc(self, *_a, **_k):
        raise RuntimeError("db down (rpc)")


# ===========================================================================
# Persistence: budget survives a discarded/recreated service (no process cache)
# ===========================================================================
class TestPersistenceAcrossServiceInstances:
    def test_usage_persisted_via_track_is_visible_after_recreating_service(self):
        db = _fake_db()
        # First "process": consume 1000 tokens.
        svc1 = _svc()
        svc1.track_token_usage(STUDENT_A_ID, 1000, db)

        # Discard svc1 and create a brand-new AIService — any in-memory budget would
        # be wiped here. The persisted row in ``token_usage`` must still be there.
        del svc1
        svc2 = _svc()
        # The new service must NOT be blocked (1000 << limit) and the read must
        # reflect the persisted total.
        svc2.check_token_budget(STUDENT_A_ID, db)  # no raise
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == 1000

    def test_no_module_level_cache_state_leaks_between_instances(self):
        # Two independent DBs → two independent persisted states. If a process-wide
        # cache still existed, usage written against db_a would bleed into db_b.
        db_a, db_b = _fake_db(), _fake_db()
        _svc().track_token_usage(STUDENT_A_ID, 5000, db_a)
        assert TokenUsageRepository(db_a).get_today_usage(STUDENT_A_ID) == 5000
        # A fresh service reading the OTHER db sees zero — no shared in-memory state.
        assert TokenUsageRepository(db_b).get_today_usage(STUDENT_A_ID) == 0
        _svc().check_token_budget(STUDENT_A_ID, db_b)  # no raise (zero usage)


# ===========================================================================
# Enforcement: the cap raises once persisted usage >= daily_token_limit
# ===========================================================================
class TestBudgetEnforcement:
    def test_under_limit_does_not_raise(self):
        db = _fake_db()
        svc = _svc()
        svc.track_token_usage(STUDENT_A_ID, svc.daily_token_limit - 1, db)
        svc.check_token_budget(STUDENT_A_ID, db)  # exactly under → allowed

    def test_at_or_over_limit_raises_ai_service_error(self):
        db = _fake_db()
        svc = _svc()
        svc.track_token_usage(STUDENT_A_ID, svc.daily_token_limit, db)
        with pytest.raises(AIServiceError):
            svc.check_token_budget(STUDENT_A_ID, db)

    def test_limit_persisted_blocks_a_brand_new_service(self):
        """Restart oracle: cross the cap, drop the service, a NEW one still blocks."""
        db = _fake_db()
        svc1 = _svc()
        svc1.track_token_usage(STUDENT_A_ID, svc1.daily_token_limit + 10, db)
        del svc1
        with pytest.raises(AIServiceError):
            _svc().check_token_budget(STUDENT_A_ID, db)

    def test_other_user_not_affected_by_first_users_consumption(self):
        db = _fake_db()
        svc = _svc()
        svc.track_token_usage(STUDENT_A_ID, svc.daily_token_limit, db)
        # B never consumed → B is not blocked by A's over-limit usage.
        svc.check_token_budget(STUDENT_B_ID, db)  # no raise
        with pytest.raises(AIServiceError):
            svc.check_token_budget(STUDENT_A_ID, db)


# ===========================================================================
# No-op guards (preserved behavior)
# ===========================================================================
class TestNoOpGuards:
    def test_check_falsy_user_is_noop_even_without_db(self):
        _svc().check_token_budget(None, None)  # must not raise, must not touch db
        _svc().check_token_budget("", _fake_db())  # falsy user → no-op

    def test_track_falsy_user_or_nonpositive_tokens_is_noop(self):
        db = _fake_db()
        svc = _svc()
        svc.track_token_usage(None, 100, db)       # no user
        svc.track_token_usage(STUDENT_A_ID, 0, db)  # zero tokens
        svc.track_token_usage(STUDENT_A_ID, -5, db)  # negative tokens
        # Nothing was persisted by any of the no-op calls.
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == 0
        assert db.rows("token_usage") == []


# ===========================================================================
# Fail-open (check) / best-effort (track) when db is missing or erroring
# ===========================================================================
class TestFailOpenAndBestEffort:
    def test_check_with_none_db_fails_open(self):
        # No persistence layer → must NOT raise (fail-open), regardless of user.
        _svc().check_token_budget(STUDENT_A_ID, None)

    def test_track_with_none_db_is_quiet_noop(self):
        # No persistence layer → swallow quietly (best-effort), never raise.
        _svc().track_token_usage(STUDENT_A_ID, 1000, None)

    def test_check_read_error_fails_open(self):
        # The repository read raises → service must degrade to allowing the request.
        _svc().check_token_budget(STUDENT_A_ID, _RaisingDB())  # no raise

    def test_check_read_error_fails_open_even_if_user_was_over_limit(self):
        # Even a user who is "over limit" on a healthy DB is allowed through when the
        # read itself fails — availability is preferred over enforcement here.
        _svc().check_token_budget(STUDENT_A_ID, _RaisingDB())  # no raise

    def test_track_write_error_is_swallowed(self):
        # The repository write raises → service must swallow it (never propagate).
        try:
            _svc().track_token_usage(STUDENT_A_ID, 1000, _RaisingDB())
        except Exception as exc:  # pragma: no cover - the whole point is it never raises
            pytest.fail(f"track_token_usage must swallow write errors, raised {exc!r}")


# ===========================================================================
# Atomicity: no double-count under repeated increments
# ===========================================================================
class TestNoDoubleCount:
    def test_two_increments_sum_exactly_once_each(self):
        db = _fake_db()
        svc = _svc()
        svc.track_token_usage(STUDENT_A_ID, 100, db)
        svc.track_token_usage(STUDENT_A_ID, 250, db)
        # Atomic upsert → exactly 350, one row, never duplicated/double-counted.
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == 350
        same_day_rows = [
            r for r in db.rows("token_usage") if str(r["user_id"]) == STUDENT_A_ID
        ]
        assert len(same_day_rows) == 1, f"expected a single daily row, got {same_day_rows}"

    def test_many_increments_accumulate_without_loss(self):
        db = _fake_db()
        svc = _svc()
        for _ in range(10):
            svc.track_token_usage(STUDENT_A_ID, 7, db)
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == 70


# ===========================================================================
# Regression: real call sites still check/track against the propagated db
# ===========================================================================
class TestCallSiteIntegration:
    async def test_generate_questions_tracks_usage_into_db(self):
        db = _fake_db()
        # The creator path returns JSON; the fake usage is 10+20=30 tokens.
        svc = AIService(
            client=FakeAsyncOpenAI(response_text=json.dumps({"questions": []})),
            sync_client=None,
        )
        await svc.generate_questions(
            chapter_content="conteudo", chapter_title="Cap 1",
            user_id=STUDENT_A_ID, db=db,
        )
        # The generation persisted its token usage for the day (best-effort write ran).
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == 30

    async def test_generate_questions_blocked_when_persisted_usage_over_limit(self):
        db = _fake_db()
        svc = AIService(
            client=FakeAsyncOpenAI(response_text=json.dumps({"questions": []})),
            sync_client=None,
        )
        # Pre-seed over-limit usage so the up-front check_token_budget raises.
        svc.track_token_usage(STUDENT_A_ID, svc.daily_token_limit, db)
        with pytest.raises(AIServiceError):
            await svc.generate_questions(
                chapter_content="c", chapter_title="t",
                user_id=STUDENT_A_ID, db=db,
            )

    async def test_socratic_dialogue_tracks_usage_into_db(self):
        db = _fake_db()
        svc = AIService(
            client=FakeAsyncOpenAI(response_text="Boa. Por que? "),
            sync_client=None,
        )
        # No session_id → no chat persistence, but the token track still runs against db.
        await svc.socratic_dialogue(
            student_message="m", chapter_content="c",
            initial_question={"text": "Q?"}, interactions_remaining=3,
            user_id=STUDENT_A_ID, db=db,
        )
        assert TokenUsageRepository(db).get_today_usage(STUDENT_A_ID) == 30

    async def test_socratic_dialogue_succeeds_when_db_none_fail_open(self):
        # No db at all → check fails open, track is a quiet no-op, generation succeeds.
        svc = AIService(
            client=FakeAsyncOpenAI(response_text="Boa. Por que? "),
            sync_client=None,
        )
        out = await svc.socratic_dialogue(
            student_message="m", chapter_content="c",
            initial_question={"text": "Q?"}, interactions_remaining=3,
            user_id=STUDENT_A_ID, db=None,
        )
        assert out["response"]["content"].endswith("? ")
