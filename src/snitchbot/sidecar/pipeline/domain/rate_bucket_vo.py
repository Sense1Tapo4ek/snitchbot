"""Rate bucket — token bucket for Telegram API rate limiting.

Pure domain object. No I/O, no frameworks.

RL1: capacity=30, refill_rate=0.5 tokens/sec (30 tokens/min).
RL2: critical events bypass main bucket, subject to 60/min ceiling.
RL8: answerCallbackQuery does not consume the main bucket at all.
"""
import time

from snitchbot.sidecar.pipeline.domain.services.critical_ceiling_policy_service import (
    CriticalCeilingPolicy,
)

__all__ = ["RateBucket"]

_DEFAULT_CAPACITY: int = 30
_DEFAULT_REFILL_RATE: float = 0.5  # tokens per second


class RateBucket:
    """Token bucket for Telegram API rate limiting.

    Critical events bypass the main bucket but are checked against the
    60/min ceiling managed by CriticalCeilingPolicy.

    Args:
        capacity: Maximum number of tokens. Default 30 (RL1).
        refill_rate: Tokens added per second. Default 0.5 (RL1).
    """

    def __init__(
        self,
        capacity: int = _DEFAULT_CAPACITY,
        refill_rate: float = _DEFAULT_REFILL_RATE,
    ) -> None:
        self._capacity = capacity
        self._tokens = float(capacity)
        self._refill_rate = refill_rate
        self._last_refill = time.monotonic()
        self._ceiling_policy = CriticalCeilingPolicy()

    def acquire(self, *, is_critical: bool = False) -> bool:
        """Try to acquire a token.

        Critical path (RL2):
          - Bypasses main bucket.
          - Checked against 60/min ceiling.
          - Returns True if under ceiling, False if ceiling exceeded.

        Non-critical path (RL1):
          - Refills bucket based on elapsed time.
          - Consumes one token if available.
          - Returns True if token acquired, False if bucket empty.

        Args:
            is_critical: True for critical-severity events.

        Returns:
            True if the action is allowed, False if it should be dropped.
        """
        if is_critical:
            return self._ceiling_policy.is_critical_allowed()

        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    @property
    def tokens(self) -> float:
        """Current token count (read-only snapshot)."""
        return self._tokens

    @property
    def max_tokens(self) -> int:
        """Maximum token capacity."""
        return self._capacity

    def _refill(self) -> None:
        """Refill tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self._refill_rate
        if added > 0:
            self._tokens = min(self._tokens + added, float(self._capacity))
            self._last_refill = now
