"""Unit tests for lifecycle event builder service — Task 4.8.

Spec: docs/superpowers/specs/2026-04-11-event-model-design.md §4.6
Invariants covered:
- E2: lifecycle severity is None
- CI18: second shutdown call is no-op (dedup)
- CI33: startup has phase=startup, reason=init
- CI34: shutdown sets _sent_shutdown_event flag
"""
import os

import pytest

from snitchbot import __version__
import snitchbot.client.domain.services.lifecycle_service as lifecycle_mod
from snitchbot.client.domain.services.lifecycle_service import (
    build_shutdown_event,
    build_startup_event,
    reset_lifecycle_state,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset module-level flag before and after each test (fork safety)."""
    reset_lifecycle_state()
    yield
    reset_lifecycle_state()


class TestStartupEvent:
    def test_startup_has_phase_startup_reason_init(self):
        """
        Given service name 'my-service',
        When building a startup event,
        Then payload has phase='startup' and reason='init' (E2, CI33).
        """
        event = build_startup_event(service="my-service")
        assert event["payload"]["phase"] == "startup"
        assert event["payload"]["reason"] == "init"

    def test_startup_severity_is_none(self):
        """
        Given any service name,
        When building a startup event,
        Then severity is None (E2 — lifecycle has no severity).
        """
        event = build_startup_event(service="svc")
        assert event["severity"] is None

    def test_lifecycle_kind_is_lifecycle(self):
        """
        Given any startup event,
        When inspecting the kind,
        Then it equals 'lifecycle'.
        """
        event = build_startup_event(service="svc")
        assert event["kind"] == "lifecycle"

    def test_startup_has_standard_envelope_fields(self):
        """
        Given a startup event,
        When checking envelope fields,
        Then v=1, ts (float), pid (int), trace_id=None, context=None are present.
        """
        event = build_startup_event(service="svc")
        assert event["v"] == __version__
        assert isinstance(event["ts"], float)
        assert event["pid"] == os.getpid()
        assert event["trace_id"] is None
        assert event["context"] is None


class TestShutdownEvent:
    @pytest.mark.parametrize("reason", ["sigterm", "crash", "clean_exit"])
    def test_shutdown_variants_for_each_reason(self, reason: str):
        """
        Given each valid shutdown reason,
        When building a shutdown event,
        Then the event payload contains the correct reason and phase='shutdown'.
        """
        reset_lifecycle_state()
        event = build_shutdown_event(reason=reason)
        assert event is not None
        assert event["payload"]["phase"] == "shutdown"
        assert event["payload"]["reason"] == reason

    def test_shutdown_sets_sent_flag(self):
        """
        Given _sent_shutdown_event is False,
        When building a shutdown event,
        Then _sent_shutdown_event is set to True (CI34).
        """
        assert lifecycle_mod._sent_shutdown_event is False
        build_shutdown_event(reason="clean_exit")
        assert lifecycle_mod._sent_shutdown_event is True

    def test_second_shutdown_returns_none(self):
        """
        Given a shutdown event already sent,
        When calling build_shutdown_event again,
        Then None is returned (CI18 — dedup, second shutdown is no-op).
        """
        first = build_shutdown_event(reason="clean_exit")
        assert first is not None
        second = build_shutdown_event(reason="sigterm")
        assert second is None

    def test_shutdown_includes_exit_code_when_provided(self):
        """
        Given exit_code=1,
        When building a shutdown event,
        Then payload['exit_code'] == 1.
        """
        event = build_shutdown_event(reason="sigterm", exit_code=1)
        assert event is not None
        assert event["payload"]["exit_code"] == 1

    def test_shutdown_exit_code_none_when_not_provided(self):
        """
        Given no exit_code,
        When building a shutdown event,
        Then payload['exit_code'] is None.
        """
        event = build_shutdown_event(reason="clean_exit")
        assert event is not None
        assert event["payload"]["exit_code"] is None

    def test_shutdown_severity_is_none(self):
        """
        Given any shutdown event,
        When checking severity,
        Then it is None (E2 — lifecycle kind).
        """
        event = build_shutdown_event(reason="sigterm")
        assert event is not None
        assert event["severity"] is None


class TestLifecycleFingerprint:
    def test_lifecycle_fingerprint_is_none(self):
        """D7: lifecycle events should not be fingerprinted."""
        from snitchbot.shared.domain.services.fingerprint_service import compute_fingerprint
        from snitchbot.shared.domain import Event, EventKind, LifecyclePayload

        event = Event(
            v=__version__,
            ts=1.0,
            kind=EventKind.LIFECYCLE,
            severity=None,
            pid=1,
            trace_id=None,
            context=None,
            payload=LifecyclePayload(phase="startup", reason="init"),
        )
        assert compute_fingerprint(event) is None


class TestResetLifecycleState:
    def test_reset_clears_flag(self):
        """
        Given _sent_shutdown_event is True,
        When calling reset_lifecycle_state,
        Then _sent_shutdown_event is False again.
        """
        build_shutdown_event(reason="clean_exit")
        assert lifecycle_mod._sent_shutdown_event is True
        reset_lifecycle_state()
        assert lifecycle_mod._sent_shutdown_event is False
