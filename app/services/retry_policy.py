"""
Retry Policy Service
====================
Centralized retry logic với error classification, exponential backoff, và circuit breaker.

Config structure trong app_config:
{
    "RETRY_POLICY_CONFIG": {
        "enabled": true,
        "error_classification": {
            "deterministic": ["insufficient balance", "margin insufficient", ...],
            "temporary": ["timeout", "network", "connection"],
            "rate_limit": ["too many requests", "rate limit"]
        },
        "retry_strategies": {
            "deterministic": {"max_retries": 0},
            "temporary": {"max_retries": 5, "backoff": "exponential", "initial": 10},
            "rate_limit": {"max_retries": 3, "backoff": "fixed", "seconds": 60}
        },
        "circuit_breaker": {
            "enabled": true,
            "failure_threshold": 5,
            "cooldown_seconds": 300
        }
    }
}
"""

import random
import time
from datetime import timedelta, datetime
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass

from app.core.time_utils import ensure_utc, utc_now


@dataclass
class RetryStrategy:
    max_retries: int
    backoff_type: str  # "exponential" | "fixed" | "none"
    initial_seconds: int = 10
    max_seconds: int = 300
    fixed_seconds: int = 60


@dataclass
class RetryDecision:
    should_retry: bool
    next_retry_at: Optional[datetime]
    retry_count: int
    max_retries: int
    error_type: str
    reason: str


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, cooldown_seconds: int = 300):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.state = "closed"  # "closed" | "open" | "half_open"

    def record_success(self):
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self):
        self.failure_count += 1
        self.last_failure_time = utc_now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "open"

    def can_attempt(self) -> bool:
        if self.state == "closed":
            return True
        
        if self.state == "open":
            if self.last_failure_time:
                cooldown_end = ensure_utc(self.last_failure_time) + timedelta(seconds=self.cooldown_seconds)
                if utc_now() >= cooldown_end:
                    self.state = "half_open"
                    return True
            return False
        
        if self.state == "half_open":
            return True
        
        return False


class RetryPolicyService:
    _instance: Optional['RetryPolicyService'] = None
    _circuit_breaker: Optional[CircuitBreaker] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._config_cache: Optional[Dict] = None
            self._config_cache_time: float = 0
            self._cache_ttl = 30  # seconds

    def _get_config(self) -> Dict:
        """Load retry policy config từ DB với caching."""
        now = time.time()
        if self._config_cache and (now - self._config_cache_time < self._cache_ttl):
            return self._config_cache

        try:
            from app.services.config_service import get_runtime_config
            cfg = get_runtime_config()
            self._config_cache = cfg.get("RETRY_POLICY_CONFIG", self._get_default_config())
            self._config_cache_time = now
            return self._config_cache
        except Exception:
            return self._get_default_config()

    def _get_default_config(self) -> Dict:
        """Default config nếu không có trong DB."""
        return {
            "enabled": True,
            "error_classification": {
                "deterministic": [
                    "insufficient balance",
                    "margin is insufficient",
                    "leverage failed",
                    "qty too small",
                    "actual notional too small",
                    "order would immediately trigger",
                    "price is outside the price band",
                    "apikey permission",
                    "symbol not trading",
                    "set_leverage_failed",
                ],
                "temporary": [
                    "timeout",
                    "network",
                    "connection",
                    "connection reset",
                    "connection refused",
                ],
                "rate_limit": [
                    "too many requests",
                    "rate limit",
                    "429",
                ]
            },
            "retry_strategies": {
                "duplicate_guard": {
                    "max_retries": 0,
                    "backoff": "none"
                },
                "deterministic": {
                    "max_retries": 0,
                    "backoff": "none"
                },
                "temporary": {
                    "max_retries": 5,
                    "backoff": "exponential",
                    "initial": 10,
                    "max": 300
                },
                "rate_limit": {
                    "max_retries": 3,
                    "backoff": "fixed",
                    "seconds": 60
                }
            },
            "circuit_breaker": {
                "enabled": True,
                "failure_threshold": 5,
                "cooldown_seconds": 300
            }
        }

    def _classify_error(self, error_msg: str) -> str:
        """Phân loại error thành deterministic/temporary/rate_limit."""
        if not error_msg:
            return "temporary"
        
        error_lower = error_msg.lower()
        config = self._get_config()

        if "duplicate_open_limit_detected" in error_lower:
            return "duplicate_guard"
        
        if not config.get("enabled", True):
            return "temporary"
        
        classification = config.get("error_classification", {})
        
        # Check deterministic errors first
        for pattern in classification.get("deterministic", []):
            if pattern.lower() in error_lower:
                return "deterministic"
        
        # Check rate limit errors
        for pattern in classification.get("rate_limit", []):
            if pattern.lower() in error_lower:
                return "rate_limit"
        
        # Check temporary errors
        for pattern in classification.get("temporary", []):
            if pattern.lower() in error_lower:
                return "temporary"
        
        # Default to temporary for unknown errors
        return "temporary"

    def _get_retry_strategy(self, error_type: str) -> RetryStrategy:
        """Get retry strategy cho error type."""
        config = self._get_config()
        strategies = config.get("retry_strategies", {})
        if error_type == "duplicate_guard" and error_type not in strategies:
            strategy_config = {"max_retries": 0, "backoff": "none"}
        else:
            strategy_config = strategies.get(error_type, strategies.get("temporary", {}))
        
        backoff_type = strategy_config.get("backoff", "exponential")
        
        return RetryStrategy(
            max_retries=strategy_config.get("max_retries", 1),
            backoff_type=backoff_type,
            initial_seconds=strategy_config.get("initial", 10),
            max_seconds=strategy_config.get("max", 300),
            fixed_seconds=strategy_config.get("seconds", 60)
        )

    def _calculate_backoff(self, strategy: RetryStrategy, attempt: int) -> int:
        """Calculate backoff seconds với jitter để tránh thundering herd."""
        if strategy.backoff_type == "none":
            return 0
        
        if strategy.backoff_type == "fixed":
            base = strategy.fixed_seconds
        elif strategy.backoff_type == "exponential":
            base = strategy.initial_seconds * (2 ** attempt)
            base = min(base, strategy.max_seconds)
        else:
            base = strategy.initial_seconds
        
        # Add jitter: ±20% của base
        jitter = int(base * 0.2 * random.random())
        return base + jitter

    def _check_circuit_breaker(self) -> Tuple[bool, str]:
        """Check nếu circuit breaker cho phép retry."""
        config = self._get_config()
        cb_config = config.get("circuit_breaker", {})
        
        if not cb_config.get("enabled", False):
            return True, "circuit_breaker_disabled"
        
        if self._circuit_breaker is None:
            self._circuit_breaker = CircuitBreaker(
                failure_threshold=cb_config.get("failure_threshold", 5),
                cooldown_seconds=cb_config.get("cooldown_seconds", 300)
            )
        
        can_attempt = self._circuit_breaker.can_attempt()
        reason = f"circuit_breaker_{self._circuit_breaker.state}"
        
        return can_attempt, reason

    def record_success(self):
        """Record successful operation cho circuit breaker."""
        if self._circuit_breaker:
            self._circuit_breaker.record_success()

    def record_failure(self):
        """Record failed operation cho circuit breaker."""
        if self._circuit_breaker:
            self._circuit_breaker.record_failure()

    def should_retry(
        self,
        error_msg: str,
        current_attempt: int,
        initial_attempt_time: Optional[datetime] = None
    ) -> RetryDecision:
        """
        Determine nếu nên retry operation.
        
        Args:
            error_msg: Error message từ previous attempt
            current_attempt: Failed attempt count already recorded for this operation
            initial_attempt_time: Time của first attempt (for timeout check)
        
        Returns:
            RetryDecision với should_retry, next_retry_at, và metadata
        """
        config = self._get_config()
        failed_attempts = max(0, int(current_attempt or 0))
        
        if not config.get("enabled", True):
            # Fallback to old behavior: retry 1 time với 10s backoff
            if failed_attempts <= 1:
                next_retry = utc_now() + timedelta(seconds=10)
                return RetryDecision(
                    should_retry=True,
                    next_retry_at=next_retry,
                    retry_count=max(1, failed_attempts),
                    max_retries=1,
                    error_type="fallback",
                    reason="retry_policy_disabled"
                )
            else:
                return RetryDecision(
                    should_retry=False,
                    next_retry_at=None,
                    retry_count=failed_attempts,
                    max_retries=1,
                    error_type="fallback",
                    reason="retry_policy_disabled_max_reached"
                )
        
        # Check circuit breaker
        can_attempt, cb_reason = self._check_circuit_breaker()
        if not can_attempt:
            # Circuit breaker open: return pause decision with backoff
            # Instead of rejecting, schedule retry after circuit breaker cooldown
            cb_config = self._get_config().get("circuit_breaker", {})
            cooldown = cb_config.get("cooldown_seconds", 300)
            next_retry = utc_now() + timedelta(seconds=cooldown)
            return RetryDecision(
                should_retry=True,  # Still retry but with long backoff
                next_retry_at=next_retry,
                retry_count=failed_attempts,
                max_retries=999,  # Effectively infinite for circuit breaker
                error_type="circuit_breaker",
                reason=f"circuit_breaker_pause_{cb_reason}"
            )
        
        # Classify error
        error_type = self._classify_error(error_msg)
        strategy = self._get_retry_strategy(error_type)
        
        # Record failure for circuit breaker on exchange/network transient errors.
        # Local duplicate guards are intentionally excluded.
        if error_type in ("temporary", "rate_limit"):
            self.record_failure()
        
        # Check nếu đã hết retries
        if failed_attempts > strategy.max_retries:
            return RetryDecision(
                should_retry=False,
                next_retry_at=None,
                retry_count=failed_attempts,
                max_retries=strategy.max_retries,
                error_type=error_type,
                reason="max_retries_exceeded"
            )
        
        # Calculate next retry time
        backoff_seconds = self._calculate_backoff(strategy, max(0, failed_attempts - 1))
        next_retry_at = utc_now() + timedelta(seconds=backoff_seconds)
        
        return RetryDecision(
            should_retry=True,
            next_retry_at=next_retry_at,
            retry_count=max(1, failed_attempts),
            max_retries=strategy.max_retries,
            error_type=error_type,
            reason=f"retry_with_{strategy.backoff_type}_backoff"
        )

    def invalidate_cache(self):
        """Invalidate config cache để force reload."""
        self._config_cache = None
        self._config_cache_time = 0


# Global instance
_retry_policy_service = RetryPolicyService()

def get_retry_policy_service() -> RetryPolicyService:
    return _retry_policy_service
