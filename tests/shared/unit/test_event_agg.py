"""Unit tests for the Event envelope aggregate.

Spec: ``docs/superpowers/specs/2026-04-11-event-model-design.md`` §2 and §12.
Invariants covered: E1 (envelope shape), E2 (severity rules), E7 (type
constraints). Validation logic lives in Task 1.4's validation service — this
module only tests structural dataclass concerns.
"""
from dataclasses import FrozenInstanceError, fields

import pytest

from snitchbot import __version__
from snitchbot.shared.domain import (
    CustomPayload,
    Event,
    EventKind,
    LifecyclePayload,
)


def _make_custom_payload() -> CustomPayload:
    return CustomPayload(text="hi", extras=None, exception=None)


def _make_lifecycle_payload() -> LifecyclePayload:
    return LifecyclePayload(phase="startup", reason="init")


def _make_event(**overrides: object) -> Event:
    base: dict[str, object] = dict(
        v=__version__,
        ts=1712828400.123,
        kind=EventKind.CUSTOM,
        severity="warning",
        pid=12345,
        trace_id="abc123",
        context={"user_id": 42},
        payload=_make_custom_payload(),
    )
    base.update(overrides)
    return Event(**base)  # type: ignore[arg-type]


class TestEventStructure:
    def test_event_required_fields_present(self) -> None:
        """
        Given all required envelope fields,
        When constructing Event,
        Then construction succeeds. (E1)
        """
        event = _make_event()
        assert event.v == __version__
        assert event.kind is EventKind.CUSTOM
        assert event.severity == "warning"
        assert event.pid == 12345

    def test_event_has_all_envelope_fields(self) -> None:
        """
        Given the Event dataclass,
        When inspecting its fields,
        Then v, ts, kind, severity, pid, trace_id, context, payload are all present. (E1)
        """
        names = {f.name for f in fields(Event)}
        assert names == {
            "v",
            "ts",
            "kind",
            "severity",
            "pid",
            "trace_id",
            "context",
            "payload",
        }

    def test_event_slots_defined(self) -> None:
        """
        Given the Event class,
        When inspecting __slots__,
        Then slots are defined (frozen + slots + kw_only).
        """
        assert hasattr(Event, "__slots__")

    def test_event_is_frozen(self) -> None:
        """
        Given an Event instance,
        When assigning to a field,
        Then FrozenInstanceError is raised. (E1 — immutability)
        """
        event = _make_event()
        with pytest.raises(FrozenInstanceError):
            event.v = 2  # type: ignore[misc]


class TestEventFieldSemantics:
    def test_event_accepts_none_severity_for_lifecycle(self) -> None:
        """
        Given kind=LIFECYCLE and severity=None,
        When constructing Event,
        Then it succeeds. (E2)
        """
        event = _make_event(
            kind=EventKind.LIFECYCLE,
            severity=None,
            payload=_make_lifecycle_payload(),
        )
        assert event.severity is None
        assert event.kind is EventKind.LIFECYCLE

    def test_event_accepts_string_trace_id_or_none(self) -> None:
        """
        Given trace_id as string or None,
        When constructing Event,
        Then both variants succeed. (E1)
        """
        assert _make_event(trace_id="abc").trace_id == "abc"
        assert _make_event(trace_id=None).trace_id is None

    def test_event_context_can_be_dict_or_none(self) -> None:
        """
        Given context as dict or None,
        When constructing Event,
        Then both variants succeed. (E10)
        """
        assert _make_event(context={"a": 1}).context == {"a": 1}
        assert _make_event(context=None).context is None

    def test_event_ts_is_float(self) -> None:
        """
        Given ts as float,
        When constructing Event,
        Then ts is retained as float. (E7)
        """
        event = _make_event(ts=1712828400.5)
        assert isinstance(event.ts, float)

    def test_event_pid_is_int(self) -> None:
        """
        Given pid as int,
        When constructing Event,
        Then pid is retained as int. (E7)
        """
        event = _make_event(pid=99)
        assert isinstance(event.pid, int)
