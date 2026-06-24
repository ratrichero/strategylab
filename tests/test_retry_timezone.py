import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.services.retry_policy import RetryDecision, RetryPolicyService
from app.services.live.protection_service import set_breakeven_retry_backoff


class RetryTimezoneTests(unittest.TestCase):
    def test_retry_policy_returns_aware_next_retry_at(self):
        service = RetryPolicyService()
        decision = service.should_retry("timeout", 0)
        self.assertIsNotNone(decision.next_retry_at)
        self.assertIsNotNone(decision.next_retry_at.tzinfo)

    def test_breakeven_backoff_accepts_naive_retry_datetime(self):
        trade = SimpleNamespace(market_context={})
        naive_next_retry = datetime.utcnow() + timedelta(seconds=10)
        decision = RetryDecision(
            should_retry=True,
            next_retry_at=naive_next_retry,
            retry_count=1,
            max_retries=1,
            error_type="temporary",
            reason="test",
        )

        with patch("app.services.live.protection_service.get_retry_policy_service") as factory:
            factory.return_value.should_retry.return_value = decision
            set_breakeven_retry_backoff(trade, "TIMEOUT")

        self.assertIn("breakeven_next_retry_at", trade.market_context)
        self.assertIn("+00:00", trade.market_context["breakeven_next_retry_at"])


if __name__ == "__main__":
    unittest.main()
