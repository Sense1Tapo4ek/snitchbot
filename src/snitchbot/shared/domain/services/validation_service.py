"""Event validation service.

This module contains a pure, side-effect-free :func:`validate` that inspects
either a raw dict (pre-codec envelope) or an :class:`Event` aggregate and
returns a list of human-readable error strings. An empty list means valid.

The function never raises and never mutates its input. It implements the
full §8 rule-set in a single pass so that callers receive *all* problems at
once — the spec explicitly prefers error aggregation over fail-fast so
that producers can be debugged holistically.

A thin wrapper :func:`validate_or_raise` converts a non-empty error list
into an :class:`EventValidationError` for callers that prefer the raise
style (see invariant E5).

Covers invariants:
- **E1** — required envelope fields must be present; missing field = invalid.
- **E2** — ``severity`` is ``None`` for lifecycle, one of
  ``warning/error/critical`` otherwise.
- **E7** — timestamps are wall-clock UTC floats (strict, no int coercion).
"""
from collections.abc import Mapping
from typing import Any

from snitchbot.shared.domain.errors import EventValidationError
from snitchbot.shared.domain.event_agg import Event
from snitchbot.shared.domain.event_kind_vo import EventKind
from snitchbot.shared.domain.payloads import (
    AnomalyPayload,
    CrashPayload,
    CustomPayload,
    LifecyclePayload,
    SlowCallPayload,
    WatchdogPayload,
)

_KNOWN_KINDS: frozenset[str] = frozenset(k.value for k in EventKind)
_VALID_SEVERITIES: frozenset[str] = frozenset({"warning", "error", "critical"})
_LIFECYCLE_KIND: str = EventKind.LIFECYCLE.value

_PAYLOAD_VO_TYPES: tuple[type, ...] = (
    CrashPayload,
    CustomPayload,
    SlowCallPayload,
    WatchdogPayload,
    AnomalyPayload,
    LifecyclePayload,
)

# Sentinel to distinguish "key absent" from "key present with value None".
_MISSING: Any = object()

def _field(obj: Any, name: str) -> Any:
    """Return the named field from a dict or Event aggregate, or ``_MISSING``.

    Pure read; never mutates ``obj``.
    """
    if isinstance(obj, Mapping):
        if name in obj:
            return obj[name]
        return _MISSING
    # Event aggregate: attributes always present (dataclass) — use getattr.
    return getattr(obj, name, _MISSING)

def _is_strict_float(value: Any) -> bool:
    """Strictly a ``float``. Reject ``bool`` and ``int`` (spec §8)."""
    return isinstance(value, float) and not isinstance(value, bool)

def _is_strict_int(value: Any) -> bool:
    """Strictly a non-bool ``int``."""
    return isinstance(value, int) and not isinstance(value, bool)

def validate(event: Event | Mapping[str, Any]) -> list[str]:
    """Return a list of validation error strings for ``event``.

    Accepts either a raw dict (pre-codec form) or an :class:`Event` aggregate.
    Pure: never raises, never mutates input. Empty list means valid.
    """
    errors: list[str] = []

    is_event_agg = isinstance(event, Event)

    # ---- v ---------------------------------------------------------------
    v = _field(event, "v")
    if v is _MISSING or not isinstance(v, str) or not v:
        errors.append(f"bad_version:{v if v is not _MISSING else 'missing'}")

    # ---- kind ------------------------------------------------------------
    kind_raw = _field(event, "kind")
    if kind_raw is _MISSING:
        errors.append("unknown_kind:missing")
        kind_value: str | None = None
    else:
        # Event aggregate stores EventKind; dicts store the raw string.
        kind_value = (
            kind_raw.value if isinstance(kind_raw, EventKind) else kind_raw
        )
        if kind_value not in _KNOWN_KINDS:
            errors.append(f"unknown_kind:{kind_value}")

    # ---- severity (depends on kind) --------------------------------------
    severity = _field(event, "severity")
    if severity is _MISSING:
        errors.append("severity:missing")
    elif kind_value is not None and kind_value in _KNOWN_KINDS:
        if kind_value == _LIFECYCLE_KIND:
            if severity is not None:
                errors.append(
                    f"severity:must_be_none_for_lifecycle:{severity!r}"
                )
        else:
            if severity not in _VALID_SEVERITIES:
                errors.append(
                    f"severity:invalid_for_kind_{kind_value}:{severity!r}"
                )

    # ---- ts --------------------------------------------------------------
    ts = _field(event, "ts")
    if ts is _MISSING:
        errors.append("ts:missing")
    elif not _is_strict_float(ts):
        errors.append(f"ts:not_float:{type(ts).__name__}")
    elif ts < 0:
        errors.append(f"ts:negative:{ts}")

    # ---- pid -------------------------------------------------------------
    pid = _field(event, "pid")
    if pid is _MISSING:
        errors.append("pid:missing")
    elif not _is_strict_int(pid):
        errors.append(f"pid:not_int:{type(pid).__name__}")
    elif pid <= 0:
        errors.append(f"pid:non_positive:{pid}")

    # ---- trace_id (optional type check) ----------------------------------
    trace_id = _field(event, "trace_id")
    if trace_id is _MISSING:
        errors.append("trace_id:missing")
    elif trace_id is not None and not isinstance(trace_id, str):
        errors.append(f"trace_id:not_str_or_none:{type(trace_id).__name__}")

    # ---- context ---------------------------------------------------------
    # The key MUST be present. Value may be None or a dict. Event aggregate
    # always has the attribute so this only matters for dict form.
    context = _field(event, "context")
    if context is _MISSING:
        errors.append("context:missing")
    elif context is not None and not isinstance(context, dict):
        errors.append(f"context:not_dict_or_none:{type(context).__name__}")

    # ---- payload ---------------------------------------------------------
    payload = _field(event, "payload")
    if payload is _MISSING:
        errors.append("payload:missing")
    else:
        if is_event_agg:
            if not isinstance(payload, _PAYLOAD_VO_TYPES):
                errors.append(
                    f"payload:not_payload_vo:{type(payload).__name__}"
                )
        else:
            if not isinstance(payload, dict):
                errors.append(
                    f"payload:not_dict:{type(payload).__name__}"
                )

    return errors

def validate_or_raise(event: Event | Mapping[str, Any]) -> None:
    """Raise :class:`EventValidationError` if ``event`` is invalid.

    Thin wrapper around :func:`validate`. No-op when the event is valid.
    """
    errors = validate(event)
    if errors:
        raise EventValidationError(f"Event invalid: {errors}", errors=errors)
