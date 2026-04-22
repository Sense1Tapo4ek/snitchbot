"""Watchdog payload VO + StuckTask VO.

"""
from dataclasses import dataclass

@dataclass(frozen=True, slots=True, kw_only=True)
class StuckTask:
    """A single stuck task snapshot captured by the watchdog (spec §4.4).

    ``coro`` is the dotted import path of the coroutine function — this is
    the single fingerprint input for watchdog events (spec §6).
    ``stack`` is a tuple of already-rendered frame strings (max 20 frames,
    enforced by the validation service).
    """

    name: str
    coro: str
    stack: tuple[str, ...]

@dataclass(frozen=True, slots=True, kw_only=True)
class WatchdogPayload:
    """Payload for ``EventKind.WATCHDOG`` events (spec §4.4)."""

    block_duration_ms: float
    threshold_ms: float
    loop_id: str
    stuck_tasks: tuple[StuckTask, ...]
