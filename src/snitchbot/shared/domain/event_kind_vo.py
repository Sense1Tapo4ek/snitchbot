"""EventKind enum for the snitchbot telemetry event model.

Six kinds cover every source of events: crash, custom, slow_call, watchdog,
anomaly, lifecycle. All kinds except ``lifecycle`` carry a severity and pass
through the dedup -> rate-limit -> render -> send pipeline. ``lifecycle`` uses
a separate rendering path and has ``severity=None``.

Implemented as ``(str, Enum)`` (not ``StrEnum``) for Python 3.10 compatibility.
"""
from enum import Enum

class EventKind(str, Enum):
    """The six telemetry event kinds."""

    CRASH = "crash"
    CUSTOM = "custom"
    SLOW_CALL = "slow_call"
    WATCHDOG = "watchdog"
    ANOMALY = "anomaly"
    LIFECYCLE = "lifecycle"

#: Event kinds that carry a severity and flow through the alert pipeline.
#: ``LIFECYCLE`` is excluded — it has ``severity=None`` and uses a separate
#: lifecycle renderer path (see spec §4.6).
KINDS_WITH_SEVERITY: frozenset[EventKind] = frozenset(
    k for k in EventKind if k is not EventKind.LIFECYCLE
)
