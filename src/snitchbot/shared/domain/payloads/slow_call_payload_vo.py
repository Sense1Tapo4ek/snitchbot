"""Slow-call payload VO.

"""
from dataclasses import dataclass

@dataclass(frozen=True, slots=True, kw_only=True)
class Location:
    """Point of definition for a slow-called function (spec §4.3)."""

    file: str
    line: int

@dataclass(frozen=True, slots=True, kw_only=True)
class SlowCallPayload:
    """Payload for ``EventKind.SLOW_CALL`` events.

    Spec §4.3 forbids ``args_summary``/previews (non-goal, §13).
    """

    func_qualname: str
    duration_ms: float
    threshold_ms: float
    is_async: bool
    location: Location
