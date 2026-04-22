"""Critical ceiling policy service.

Pure domain service. No I/O, no frameworks.

Responsibilities:
1. Classify whether a given TG API action name consumes the main bucket (RL8).
2. Track and enforce the 60/min hard ceiling for critical events (RL2).
"""
import time

__all__ = ["CriticalCeilingPolicy"]

# TG API action names that do NOT consume the main rate-limit bucket (RL8).
_NON_CONSUMING_ACTIONS: frozenset[str] = frozenset({"answer_callback_query"})

_CRITICAL_CEILING_PER_MINUTE: int = 60


class CriticalCeilingPolicy:
    """Stateful policy for critical-event ceiling enforcement (RL2).

    Also provides a pure classification method for main-bucket consumption (RL8).
    """

    def __init__(self, ceiling: int = _CRITICAL_CEILING_PER_MINUTE) -> None:
        self._ceiling = ceiling
        self._count: int = 0
        self._window_start: float = time.monotonic()

    # ------------------------------------------------------------------
    # RL8: bucket consumption classification
    # ------------------------------------------------------------------

    @staticmethod
    def consumes_main_bucket(action: str) -> bool:
        """Return True if the given TG API action consumes the main bucket.

        RL8: answerCallbackQuery does not consume the main bucket.
        """
        return action not in _NON_CONSUMING_ACTIONS

    # ------------------------------------------------------------------
    # RL2: critical ceiling enforcement
    # ------------------------------------------------------------------

    def is_critical_allowed(self) -> bool:
        """Check whether a critical event is allowed under the 60/min ceiling.

        Resets the window if more than 60 seconds have elapsed.
        Returns True if under ceiling, False if over.
        """
        now = time.monotonic()
        elapsed = now - self._window_start

        if elapsed >= 60.0:
            # Reset window
            self._window_start = now
            self._count = 0

        if self._count < self._ceiling:
            self._count += 1
            return True

        return False
