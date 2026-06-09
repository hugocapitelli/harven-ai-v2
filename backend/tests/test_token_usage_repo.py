"""TKN-2 — TokenUsageRepository regression suite (Phase 4, EPIC-AI).

Fail-before / pass-after oracle for the durable token-budget data layer that
replaces the volatile in-memory ``_user_token_cache`` (bug #12). Every test runs
headless against the in-process ``FakeSupabaseClient`` (no network/DB); the fake
implements TKN-1's atomic ``increment_token_usage`` RPC against its in-memory
``token_usage`` table.

Contract under test:
  * ``get_today_usage`` → ``0`` when the user has no row for the current day
    (absence == zero, never ``None``/exception).
  * ``add_usage`` → invokes the RPC and returns the post-increment daily total.
  * ``add_usage`` is additive across consecutive calls (the sum lives in the RPC).
  * ``add_usage(tokens <= 0)`` is a no-op: it never invokes the RPC (idempotent).
"""
from __future__ import annotations

from datetime import date

from conftest import STUDENT_A_ID, STUDENT_B_ID
from fakes import FakeSupabaseClient
from repositories.token_usage_repo import TokenUsageRepository


def _fake() -> FakeSupabaseClient:
    """A fake with the TKN-1 RPC enabled (mirrors a DB after the migration)."""
    return FakeSupabaseClient({"token_usage": []}, rpc_enabled=True)


def _today() -> str:
    return date.today().isoformat()


class TestTkn2TokenUsageRepo:
    # ── get_today_usage: absence == 0 ────────────────────────────────
    def test_absence_returns_zero_not_none(self):
        repo = TokenUsageRepository(_fake())
        result = repo.get_today_usage(STUDENT_A_ID)
        # Absence is zero consumption — never None, never an exception.
        assert result == 0
        assert result is not None

    def test_absence_returns_zero_only_for_other_day(self):
        # A row exists for the user, but on a DIFFERENT day → today still reads 0.
        fake = FakeSupabaseClient(
            {"token_usage": [
                {"id": "tu-old", "user_id": STUDENT_A_ID,
                 "usage_date": "2020-01-01", "tokens_used": 999},
            ]},
            rpc_enabled=True,
        )
        assert TokenUsageRepository(fake).get_today_usage(STUDENT_A_ID) == 0

    # ── add_usage: increment → new total via RPC ─────────────────────
    def test_add_usage_returns_new_total_via_rpc(self):
        fake = _fake()
        repo = TokenUsageRepository(fake)
        total = repo.add_usage(STUDENT_A_ID, 150)
        # RPC returns the post-increment total; the row is persisted for today.
        assert total == 150
        assert any(c["name"] == "increment_token_usage" for c in fake.rpc_calls)
        row = fake.find("token_usage", user_id=STUDENT_A_ID, usage_date=_today())
        assert row is not None and row["tokens_used"] == 150
        # And get_today_usage now reflects the persisted total.
        assert repo.get_today_usage(STUDENT_A_ID) == 150

    def test_two_consecutive_add_usage_sum_correctly(self):
        fake = _fake()
        repo = TokenUsageRepository(fake)
        first = repo.add_usage(STUDENT_A_ID, 100)
        second = repo.add_usage(STUDENT_A_ID, 250)
        # The sum lives in the RPC: 100 then 100+250 = 350 — no lost increment.
        assert first == 100
        assert second == 350
        assert repo.get_today_usage(STUDENT_A_ID) == 350
        # Exactly one row for (user, today) despite two writes.
        rows = [r for r in fake.rows("token_usage")
                if r["user_id"] == STUDENT_A_ID and r["usage_date"] == _today()]
        assert len(rows) == 1

    def test_add_usage_isolated_per_user(self):
        fake = _fake()
        repo = TokenUsageRepository(fake)
        repo.add_usage(STUDENT_A_ID, 100)
        repo.add_usage(STUDENT_B_ID, 40)
        # Each user's daily counter is independent (separate rows).
        assert repo.get_today_usage(STUDENT_A_ID) == 100
        assert repo.get_today_usage(STUDENT_B_ID) == 40

    # ── add_usage(tokens <= 0): no-op, never invokes the RPC ─────────
    def test_zero_tokens_is_noop_no_rpc(self):
        fake = _fake()
        repo = TokenUsageRepository(fake)
        result = repo.add_usage(STUDENT_A_ID, 0)
        assert result == 0
        # Idempotency: a non-positive increment must NOT touch the RPC or the table.
        assert not any(c["name"] == "increment_token_usage" for c in fake.rpc_calls)
        assert fake.find("token_usage", user_id=STUDENT_A_ID, usage_date=_today()) is None

    def test_negative_tokens_is_noop_no_rpc(self):
        fake = _fake()
        repo = TokenUsageRepository(fake)
        result = repo.add_usage(STUDENT_A_ID, -50)
        assert result == 0
        assert not any(c["name"] == "increment_token_usage" for c in fake.rpc_calls)
        assert fake.find("token_usage", user_id=STUDENT_A_ID, usage_date=_today()) is None

    def test_zero_tokens_returns_current_total_without_resetting(self):
        fake = _fake()
        repo = TokenUsageRepository(fake)
        repo.add_usage(STUDENT_A_ID, 200)
        # A subsequent no-op returns the existing total and never writes again.
        rpc_calls_before = len(fake.rpc_calls)
        assert repo.add_usage(STUDENT_A_ID, 0) == 200
        assert len(fake.rpc_calls) == rpc_calls_before  # no extra RPC invocation
        assert repo.get_today_usage(STUDENT_A_ID) == 200
