"""P2 fix 10 — the token-budget fail-open must be OBSERVED, never silent.

``TokenUsageRepository.get_today_usage`` swallowed read failures into a ``0``
indistinguishable from "no consumption yet", so ``check_token_budget``'s own
fail-open handler never fired: a broken ``token_usage`` table meant the daily
budget silently stopped being enforced, with no log and no counter. Pinned here:

  * a failing usage read still lets the request through (availability first) but
    logs at ERROR and increments ``AIService.budget_failopen_count``;
  * a missing db handle counts as a fail-open too;
  * a healthy read enforces the limit exactly as before (no behavior change);
  * the repo's legacy swallow-to-0 default is preserved for its internal callers,
    while ``raise_on_error=True`` surfaces the exception.
"""
from __future__ import annotations

import pytest

from conftest import STUDENT_A_ID, make_seed_tables, make_ai_service
from fakes import FakeSupabaseClient


class BrokenUsageFake(FakeSupabaseClient):
    """Fails every read of token_usage (simulates missing table / dead DB)."""

    def table(self, name):
        qb = super().table(name)
        if name == "token_usage":
            def boom():
                raise Exception('relation "token_usage" does not exist')
            qb.execute = boom
        return qb


class TestRepoContract:
    def test_default_still_swallows_to_zero(self):
        from repositories.token_usage_repo import TokenUsageRepository

        repo = TokenUsageRepository(BrokenUsageFake(make_seed_tables()))
        assert repo.get_today_usage(STUDENT_A_ID) == 0

    def test_raise_on_error_surfaces_the_failure(self):
        from repositories.token_usage_repo import TokenUsageRepository

        repo = TokenUsageRepository(BrokenUsageFake(make_seed_tables()))
        with pytest.raises(Exception, match="token_usage"):
            repo.get_today_usage(STUDENT_A_ID, raise_on_error=True)


class TestServiceAccounting:
    def test_read_failure_fails_open_but_is_counted_and_logged(self, caplog):
        service, _, _ = make_ai_service()
        assert service.budget_failopen_count == 0

        with caplog.at_level("ERROR"):
            # Must NOT raise — availability wins — but must be accounted.
            service.check_token_budget(STUDENT_A_ID, db=BrokenUsageFake(make_seed_tables()))

        assert service.budget_failopen_count == 1
        assert any("fail-open" in r.message for r in caplog.records)

    def test_missing_db_is_also_counted(self):
        service, _, _ = make_ai_service()
        service.check_token_budget(STUDENT_A_ID, db=None)
        assert service.budget_failopen_count == 1

    def test_healthy_read_still_enforces_the_limit(self):
        from services.ai_service import AIServiceError
        from datetime import date

        service, _, _ = make_ai_service()
        fake = FakeSupabaseClient(make_seed_tables())
        fake.add("token_usage", {
            "user_id": STUDENT_A_ID,
            "usage_date": date.today().isoformat(),
            "tokens_used": service.daily_token_limit + 1,
        })
        with pytest.raises(AIServiceError):
            service.check_token_budget(STUDENT_A_ID, db=fake)
        # Enforcement is not a fail-open.
        assert service.budget_failopen_count == 0

    def test_healthy_read_under_limit_passes_without_failopen(self):
        from datetime import date

        service, _, _ = make_ai_service()
        fake = FakeSupabaseClient(make_seed_tables())
        fake.add("token_usage", {
            "user_id": STUDENT_A_ID,
            "usage_date": date.today().isoformat(),
            "tokens_used": 10,
        })
        service.check_token_budget(STUDENT_A_ID, db=fake)
        assert service.budget_failopen_count == 0
