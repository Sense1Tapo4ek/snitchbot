"""Unit tests for the event validation service.

Spec: ``docs/superpowers/specs/2026-04-11-event-model-design.md`` §8.
Plan:  ``docs/superpowers/plans/2026-04-11-implementation-plan.md`` Task 1.4.

Covers invariants:
- **E1** — envelope must carry all required fields; missing = invalid.
- **E2** — ``severity`` must be ``None`` for lifecycle, in the allowed set otherwise.
- **E7** — timestamps are wall-clock UTC floats (not ints, not negative).

The validation service is a pure function: it never raises, never mutates
input, and returns a list of human-readable error strings. An empty list
means the event is valid. A helper ``validate_or_raise`` wraps the list into
an :class:`EventValidationError` for callers that prefer the raise-style API.
"""
import pytest

from snitchbot import __version__
from snitchbot.shared.domain.errors import EventValidationError
from snitchbot.shared.domain.event_agg import Event
from snitchbot.shared.domain.event_kind_vo import EventKind
from snitchbot.shared.domain.payloads import (
    CrashPayload,
    LifecyclePayload,
    StackFrame,
)
from snitchbot.shared.domain.services import validate, validate_or_raise


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _crash_payload_dict() -> dict:
    return {
        "exception_type": "ValueError",
        "message": "bad",
        "stack": [],
        "thread": "MainThread",
        "origin": "sys_excepthook",
    }


def _crash_payload_vo() -> CrashPayload:
    return CrashPayload(
        exception_type="ValueError",
        message="bad",
        stack=(
            StackFrame(file="app.py", line=1, func="main", code=None, is_user_code=True),
        ),
        thread="MainThread",
        origin="sys_excepthook",
    )


def _valid_crash_dict() -> dict:
    return {
        "v": __version__,
        "ts": 1712828400.123,
        "kind": "crash",
        "severity": "error",
        "pid": 12345,
        "trace_id": "abc",
        "context": {"user_id": 42},
        "payload": _crash_payload_dict(),
    }


def _valid_lifecycle_dict() -> dict:
    return {
        "v": __version__,
        "ts": 1712828400.0,
        "kind": "lifecycle",
        "severity": None,
        "pid": 12345,
        "trace_id": None,
        "context": None,
        "payload": {"phase": "startup", "reason": "init"},
    }


def _valid_crash_event() -> Event:
    return Event(
        v=__version__,
        ts=1712828400.123,
        kind=EventKind.CRASH,
        severity="error",
        pid=12345,
        trace_id="abc",
        context={"user_id": 42},
        payload=_crash_payload_vo(),
    )


def _valid_lifecycle_event() -> Event:
    return Event(
        v=__version__,
        ts=1712828400.0,
        kind=EventKind.LIFECYCLE,
        severity=None,
        pid=12345,
        trace_id=None,
        context=None,
        payload=LifecyclePayload(phase="startup", reason="init"),
    )


# --------------------------------------------------------------------------- #
# Happy paths                                                                 #
# --------------------------------------------------------------------------- #


class TestValidateAccepts:
    def test_validate_accepts_valid_crash_event(self):
        """
        Given a well-formed crash event dict,
        When validate() is called,
        Then it returns an empty list (E1, E2, E7 all satisfied).
        """
        assert validate(_valid_crash_dict()) == []

    def test_validate_accepts_valid_lifecycle_with_none_severity(self):
        """
        Given a lifecycle event with severity=None,
        When validate() is called,
        Then it returns an empty list (E2 — lifecycle requires None).
        """
        assert validate(_valid_lifecycle_dict()) == []

    def test_validate_accepts_both_dict_and_event_forms(self):
        """
        Given the same logical event in raw-dict and Event-aggregate forms,
        When both are validated,
        Then both produce an empty error list.
        """
        assert validate(_valid_crash_dict()) == []
        assert validate(_valid_crash_event()) == []
        assert validate(_valid_lifecycle_dict()) == []
        assert validate(_valid_lifecycle_event()) == []


# --------------------------------------------------------------------------- #
# Version — E1                                                                #
# --------------------------------------------------------------------------- #


class TestValidateVersion:
    def test_validate_rejects_version_other_than_1(self):
        """
        Given an event with v=2,
        When validated,
        Then the error list contains a 'bad_version:2' entry (E1/§10).
        """
        event = _valid_crash_dict()
        event["v"] = 2
        errors = validate(event)
        assert any("bad_version" in e for e in errors)


# --------------------------------------------------------------------------- #
# Kind — E1                                                                   #
# --------------------------------------------------------------------------- #


class TestValidateKind:
    def test_validate_rejects_unknown_kind(self):
        """
        Given an event with kind='bogus',
        When validated,
        Then the error list contains 'unknown_kind:bogus' (E1, §3).
        """
        event = _valid_crash_dict()
        event["kind"] = "bogus"
        errors = validate(event)
        assert any("unknown_kind" in e for e in errors)


# --------------------------------------------------------------------------- #
# Severity — E2                                                               #
# --------------------------------------------------------------------------- #


class TestValidateSeverity:
    def test_validate_requires_severity_none_for_lifecycle(self):
        """
        Given a lifecycle event with severity='error',
        When validated,
        Then an error is reported (E2 — lifecycle MUST carry None).
        """
        event = _valid_lifecycle_dict()
        event["severity"] = "error"
        errors = validate(event)
        assert any("severity" in e for e in errors)

    def test_validate_requires_severity_in_allowed_set_for_non_lifecycle(self):
        """
        Given a crash event with severity='debug',
        When validated,
        Then an error is reported (E2 — must be warning/error/critical).
        """
        event = _valid_crash_dict()
        event["severity"] = "debug"
        errors = validate(event)
        assert any("severity" in e for e in errors)


# --------------------------------------------------------------------------- #
# ts — E7                                                                     #
# --------------------------------------------------------------------------- #


class TestValidateTimestamp:
    def test_validate_rejects_non_float_ts(self):
        """
        Given an event whose ts is an int,
        When validated,
        Then an error is reported (E7 — ts must be wall-clock float).
        """
        event = _valid_crash_dict()
        event["ts"] = 1712828400  # int, not float
        errors = validate(event)
        assert any("ts" in e for e in errors)

    def test_validate_rejects_negative_ts(self):
        """
        Given an event whose ts is negative,
        When validated,
        Then an error is reported (E7 — wall-clock UTC is non-negative).
        """
        event = _valid_crash_dict()
        event["ts"] = -1.0
        errors = validate(event)
        assert any("ts" in e for e in errors)


# --------------------------------------------------------------------------- #
# pid — E1                                                                    #
# --------------------------------------------------------------------------- #


class TestValidatePid:
    def test_validate_rejects_non_int_pid(self):
        """
        Given an event whose pid is a string,
        When validated,
        Then an error is reported (E1 — pid must be int).
        """
        event = _valid_crash_dict()
        event["pid"] = "12345"
        errors = validate(event)
        assert any("pid" in e for e in errors)

    def test_validate_rejects_negative_pid(self):
        """
        Given an event whose pid is zero or negative,
        When validated,
        Then an error is reported (pid is an OS process id, must be positive).
        """
        event = _valid_crash_dict()
        event["pid"] = 0
        errors = validate(event)
        assert any("pid" in e for e in errors)


# --------------------------------------------------------------------------- #
# payload — E1                                                                #
# --------------------------------------------------------------------------- #


class TestValidatePayload:
    def test_validate_rejects_missing_payload(self):
        """
        Given an event dict with no payload key,
        When validated,
        Then an error is reported (E1 — payload mandatory).
        """
        event = _valid_crash_dict()
        del event["payload"]
        errors = validate(event)
        assert any("payload" in e for e in errors)


# --------------------------------------------------------------------------- #
# context — E1                                                                #
# --------------------------------------------------------------------------- #


class TestValidateContext:
    def test_validate_rejects_missing_context_key_distinct_from_none(self):
        """
        Given an event dict where 'context' key is absent,
        When validated,
        Then an error is reported (E1 — field mandatory).

        And given an event dict where 'context' is present with value None,
        When validated,
        Then no context-related error is produced (None is legal).
        """
        # Absent — error.
        event = _valid_crash_dict()
        del event["context"]
        errors = validate(event)
        assert any("context" in e for e in errors)

        # Present but None — OK.
        event2 = _valid_crash_dict()
        event2["context"] = None
        assert validate(event2) == []

    def test_validate_rejects_non_dict_context_when_not_none(self):
        """
        Given an event dict where context is a list,
        When validated,
        Then an error is reported (E1 — must be dict or None).
        """
        event = _valid_crash_dict()
        event["context"] = ["not", "a", "dict"]
        errors = validate(event)
        assert any("context" in e for e in errors)


# --------------------------------------------------------------------------- #
# Multi-error aggregation                                                     #
# --------------------------------------------------------------------------- #


class TestValidateAggregates:
    def test_validate_returns_multiple_errors_for_multi_bug_event(self):
        """
        Given an event with multiple simultaneous bugs,
        When validated,
        Then all errors are reported in a single pass (no fail-fast).
        """
        event = {
            "v": 99,
            "ts": "not-a-float",
            "kind": "bogus",
            "severity": "debug",
            "pid": -1,
            "trace_id": None,
            # no context key
            # no payload key
        }
        errors = validate(event)
        assert len(errors) >= 4


# --------------------------------------------------------------------------- #
# validate_or_raise                                                           #
# --------------------------------------------------------------------------- #


class TestValidateOrRaise:
    def test_validate_or_raise_raises_on_invalid(self):
        """
        Given an invalid event,
        When validate_or_raise() is called,
        Then it raises EventValidationError.
        """
        event = _valid_crash_dict()
        event["v"] = 99
        with pytest.raises(EventValidationError):
            validate_or_raise(event)

    def test_validate_or_raise_silent_on_valid(self):
        """
        Given a valid event,
        When validate_or_raise() is called,
        Then no exception is raised.
        """
        validate_or_raise(_valid_crash_dict())
        validate_or_raise(_valid_lifecycle_dict())
