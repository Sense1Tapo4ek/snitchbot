"""Meta budget — token bucket for ⏳ rate-limit notification responses.

20 responses/min. Refill: 1 token / 3 sec (= 20/min).

Prevents feedback loop: "rate-limited" messages themselves cannot flood the
channel. After 20 ⏳ replies in a minute, the rest are silently dropped.

Pure domain, stdlib only.
"""
import time

__all__ = ["MetaBudget"]

_CAPACITY = 20
_REFILL_RATE = 1 / 3  # 1 token per 3 seconds = 20 per minute

class MetaBudget:
    """Token bucket for ⏳ rate-limit notifications (20/min, refill 1/3s).

    Not thread-safe — sidecar runs single asyncio event loop.
    """

    def __init__(
        self,
        capacity: int = _CAPACITY,
        refill_rate: float = _REFILL_RATE,
    ) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()

    def acquire(self) -> bool:
        """Consume one meta token.

        Returns:
            True if sending the ⏳ notification is allowed.
            False if silently dropped (meta budget exhausted).
        """
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self._refill_rate
        if added > 0:
            self._tokens = min(self._tokens + added, float(self._capacity))
            self._last_refill = now
