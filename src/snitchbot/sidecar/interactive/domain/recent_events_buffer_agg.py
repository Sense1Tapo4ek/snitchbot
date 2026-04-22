"""Recent events ring buffer — for /last and /status traffic counters.

Pure domain: stdlib only.
"""
from collections import deque

from snitchbot.shared.domain import RecentEvent

__all__ = ["RecentEvent", "RecentEventsBuffer"]

_DEFAULT_CAPACITY = 10_000

class RecentEventsBuffer:
    """Bounded circular buffer of recent events.

    Oldest entries are dropped when capacity is reached.
    """

    def __init__(self, capacity: int = _DEFAULT_CAPACITY) -> None:
        self._buf: deque[RecentEvent] = deque(maxlen=capacity)

    def add(self, event: RecentEvent) -> None:
        """Append an event to the buffer."""
        self._buf.append(event)

    def last_n(
        self,
        *,
        n: int,
        window_sec: float,
        now: float,
        severities: set[str] | None = None,
    ) -> list[RecentEvent]:
        """Return at most n events within window_sec, newest first.

        severities: if None, returns all. Otherwise filters by severity.
        """
        cutoff = now - window_sec
        result: list[RecentEvent] = []
        for ev in reversed(self._buf):
            if ev.ts < cutoff:
                break
            if severities is not None and ev.severity not in severities:
                continue
            result.append(ev)
            if len(result) >= n:
                break
        return result

    def traffic_counters(
        self,
        *,
        window_sec: float,
        now: float,
    ) -> dict[str, int]:
        """Count events by category within the window."""
        cutoff = now - window_sec
        counts: dict[str, int] = {
            "errors": 0,
            "warnings": 0,
            "slow_calls": 0,
            "watchdog_hits": 0,
        }
        for ev in self._buf:
            if ev.ts < cutoff:
                continue
            if ev.kind == "slow_call":
                counts["slow_calls"] += 1
            elif ev.kind == "watchdog":
                counts["watchdog_hits"] += 1
            elif ev.severity == "error" or ev.severity == "critical":
                counts["errors"] += 1
            elif ev.severity == "warning":
                counts["warnings"] += 1
        return counts

    def __len__(self) -> int:
        return len(self._buf)
