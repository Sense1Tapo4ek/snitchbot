"""Shared domain: lightweight recent-event snapshot.

Used by both the ingest adapter (recv_loop) and the interactive bounded context.
Pure stdlib — no frameworks.
"""
from dataclasses import dataclass

__all__ = ["RecentEvent"]


@dataclass(slots=True)
class RecentEvent:
    """A lightweight snapshot of one event for the recent buffer."""

    ts: float           # wall-clock Unix timestamp
    fingerprint: str | None
    severity: str | None  # "warning" | "error" | "critical" | None (lifecycle)
    exception_type: str | None
    message: str | None
    pid: int | None
    kind: str           # event kind (crash, custom, slow_call, ...)
    count: int = 1      # dedup count when event was recorded
    first_seen: float = 0.0
    at_path: str | None = None  # top user frame path:line in func()
