"""Lifecycle payload VO.

Lifecycle events always carry ``severity=None`` on the envelope (E2) and are
never fingerprinted (see spec §6).
"""
from dataclasses import dataclass
from typing import Literal

LifecyclePhase = Literal["startup", "shutdown"]
LifecycleReason = Literal["init", "sigterm", "crash", "clean_exit"]

@dataclass(frozen=True, slots=True, kw_only=True)
class LifecyclePayload:
    """Payload for ``EventKind.LIFECYCLE`` events (spec §4.6)."""

    phase: LifecyclePhase
    reason: LifecycleReason
    exit_code: int | None = None
