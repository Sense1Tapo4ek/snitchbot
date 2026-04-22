"""Tests for notify() latency and edge-cases — Task 5.5.

Invariants: P1, I9.
"""
import sys
from unittest.mock import MagicMock

import pytest


def _reset_public_api(api):
    """Helper to reset module-level state."""
    api._initialized = False
    api._initialized_pid = None
    api._stored_config = None
    api._send_event_fn = None
    api._stats.internal_errors = 0
    api._stats.init_conflict = 0
    api._stats.called_before_init = 0
    api._stats.notify_exc_info_no_exception = 0


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Reset module state before each test."""
    import snitchbot.client.ports.driving.public_api as api
    _reset_public_api(api)
    yield
    _reset_public_api(api)


class TestNotifyNeverRaisesOnBug:
    def test_notify_never_raises_on_internal_bug(self, monkeypatch):
        """
        Given _send_event_fn raises an internal exception,
        When notify() is called,
        Then it swallows the exception and increments internal_errors (P1, I9).
        """
        import snitchbot.client.ports.driving.public_api as api

        monkeypatch.setattr(api, "_init_impl", lambda **kw: None)
        api.init("svc", token="tok:123", chat_id="456")

        monkeypatch.setattr(api, "_send_event_fn", MagicMock(side_effect=RuntimeError("injected")))

        # Must not raise
        api.notify("test message")

        assert api._stats.internal_errors >= 1

    def test_notify_exc_info_true_outside_except_drops(self, monkeypatch):
        """
        Given exc_info=True but called outside an except block,
        When sys.exc_info() returns (None, None, None),
        Then notify() sends event without exception, increments notify_exc_info_no_exception.

        Spec §4.1 NA4 resolution.
        """
        import snitchbot.client.ports.driving.public_api as api

        monkeypatch.setattr(api, "_init_impl", lambda **kw: None)
        api.init("svc", token="tok:123", chat_id="456")

        sent_events = []
        monkeypatch.setattr(api, "_send_event_fn", sent_events.append)

        # Ensure we're outside an except block (sys.exc_info should be None,None,None)
        # by wrapping in a fresh context
        def call_outside_except():
            # Force clean exc info
            assert sys.exc_info() == (None, None, None)
            api.notify("msg outside except", exc_info=True)

        call_outside_except()

        # Should have incremented the counter
        assert api._stats.notify_exc_info_no_exception >= 1
        # Should still have sent the event (without exception)
        assert len(sent_events) >= 1
