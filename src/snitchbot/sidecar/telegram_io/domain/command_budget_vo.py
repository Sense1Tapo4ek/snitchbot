"""Command budget — token bucket for bot command responses.

10 responses/min. Refill: 1 token / 6 sec (= 10/min).

Pure domain, stdlib only.
"""
import math
import time

from snitchbot.shared.constants import SEPARATOR

__all__ = ["CommandBudget"]

_CAPACITY = 10
_REFILL_RATE = 1 / 6  # 1 token per 6 seconds = 10 per minute

# Commands whose rate-limited response must explicitly say "not processed"
_STATEFUL = frozenset({"mute", "unmute"})

class CommandBudget:
    """Token bucket for command responses (10/min, refill 1/6s).

    Separate from the main alert rate budget — commands do not compete
    with alert delivery.

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
        """Consume one command token.

        Returns:
            True if the command response is allowed, False if rate-limited.
        """
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def rate_limited_message(self, command: str) -> str:
        """Build a user-facing rate-limit notification string.

        Args:
            command: Command name (without slash), e.g. 'status', 'mute'.

        Returns:
            Human-readable rate-limit message per spec §13.3.
            Structured as `header + SEPARATOR + body` per invariant R1.
        """
        retry_sec = math.ceil(1.0 / self._refill_rate)
        header = f"⏳ <b>rate-limited</b> · /{command}"
        if command in _STATEFUL:
            body = f"not processed. Retry in {retry_sec}s."
        else:
            body = f"retry in {retry_sec}s"
        return f"{header}\n{SEPARATOR}\n{body}"

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self._refill_rate
        if added > 0:
            self._tokens = min(self._tokens + added, float(self._capacity))
            self._last_refill = now
