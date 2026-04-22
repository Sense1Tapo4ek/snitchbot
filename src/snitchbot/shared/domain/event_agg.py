"""Event envelope aggregate.

The ``Event`` dataclass is a structural container only — it does **not**
perform validation in ``__post_init__``. Validation lives in Task 1.4's
``validation_service`` which returns a list of errors (invariant E5). This
separation allows the validator to report all problems at once rather than
failing fast on the first bad field.
"""
from dataclasses import dataclass
from typing import Any

from .event_kind_vo import EventKind
from .payloads import (
    AnomalyPayload,
    CrashPayload,
    CustomPayload,
    LifecyclePayload,
    SlowCallPayload,
    WatchdogPayload,
)
from .severity_vo import Severity

EventPayload = (
    CrashPayload
    | CustomPayload
    | SlowCallPayload
    | WatchdogPayload
    | AnomalyPayload
    | LifecyclePayload
)

@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    """Immutable telemetry event envelope.

    Fields map 1:1 to the msgpack wire format from spec §2. ``severity`` must
    be ``None`` for ``EventKind.LIFECYCLE`` and one of ``warning/error/critical``
    otherwise — enforced by the validation service (E2), not here.
    """

    v: str
    ts: float
    kind: EventKind
    severity: Severity | None
    pid: int
    trace_id: str | None
    context: dict[str, Any] | None
    payload: EventPayload
