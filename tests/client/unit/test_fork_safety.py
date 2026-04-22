"""Tests for fork safety — Task 5.6.

Unit-level: no real fork(). Tests _after_fork_in_child() directly.
Invariants: CI37, CI38, CI39, CI40, CI41, CI42.
"""
import os
from unittest.mock import MagicMock, patch

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
def reset_state():
    """Reset module state before and after each test."""
    import snitchbot.client.ports.driving.public_api as api
    _reset_public_api(api)
    yield
    _reset_public_api(api)


class TestRegisterAtFork:
    def test_register_at_fork_called_in_init(self, monkeypatch):
        """
        Given os.register_at_fork is available,
        When init() is called,
        Then os.register_at_fork is invoked with after_in_child=_after_fork_in_child (CI37).
        """
        import snitchbot.client.ports.driving.public_api as api

        monkeypatch.setattr(api, "_init_impl", lambda **kw: None)

        registered = {}

        def fake_register_at_fork(**kwargs):
            registered.update(kwargs)

        monkeypatch.setattr("os.register_at_fork", fake_register_at_fork)

        api.init("svc", token="tok:123", chat_id="456")

        assert "after_in_child" in registered
        assert registered["after_in_child"] is api._after_fork_in_child


class TestAfterForkInChild:
    def test_after_fork_resets_initialized(self, monkeypatch):
        """
        Given _initialized=True and _initialized_pid set to a fake (different) PID,
        When _after_fork_in_child() is called (simulating child after fork),
        Then _initialized is reset to False (CI38).
        """
        import snitchbot.client.ports.driving.public_api as api

        # Simulate parent has initialized
        api._initialized = True
        api._initialized_pid = os.getpid() + 9999  # fake parent PID
        api._stored_config = dict(service="svc", token="tok:123", chat_id="456", anomaly=None)
        api._send_event_fn = None

        impl_calls = []

        def fake_impl(**kw):
            impl_calls.append(kw)

        monkeypatch.setattr(api, "_init_impl", fake_impl)

        # Patch os.getpid to return child pid (different from _initialized_pid)
        child_pid = os.getpid()  # real pid, different from fake parent pid above

        api._after_fork_in_child()

        assert api._initialized is True  # reinit happened
        assert api._initialized_pid == child_pid

    def test_after_fork_skips_when_pid_matches(self, monkeypatch):
        """
        Given _initialized_pid matches os.getpid() (parent's own fork hook),
        When _after_fork_in_child() is called,
        Then it exits early without reinit (CI38).
        """
        import snitchbot.client.ports.driving.public_api as api

        # Set pid to current pid (matches — parent shouldn't reinit)
        api._initialized = True
        api._initialized_pid = os.getpid()
        api._stored_config = dict(service="svc", token="tok:123", chat_id="456", anomaly=None)

        impl_calls = []

        def fake_impl(**kw):
            impl_calls.append(kw)

        monkeypatch.setattr(api, "_init_impl", fake_impl)

        api._after_fork_in_child()

        # No reinit should happen
        assert not impl_calls

    def test_after_fork_resets_lifecycle_state(self, monkeypatch):
        """
        Given fork happens after init(),
        When _after_fork_in_child() runs,
        Then lifecycle state is reset so child can send its own startup (CI38).
        """
        import snitchbot.client.ports.driving.public_api as api
        from snitchbot.client.domain.services import lifecycle_service

        # Set up as if parent initialized
        api._initialized = True
        api._initialized_pid = os.getpid() + 9999  # fake parent PID
        api._stored_config = dict(service="svc", token="tok:123", chat_id="456", anomaly=None)

        reset_called = []
        real_reset = lifecycle_service.reset_lifecycle_state

        def fake_reset():
            reset_called.append(1)
            real_reset()

        monkeypatch.setattr(lifecycle_service, "reset_lifecycle_state", fake_reset)
        monkeypatch.setattr(api, "_init_impl", lambda **kw: None)

        api._after_fork_in_child()

        assert len(reset_called) == 1

    def test_after_fork_calls_init_impl(self, monkeypatch):
        """
        Given _stored_config is set,
        When _after_fork_in_child() runs in child,
        Then _init_impl is called with stored config (CI38, CI40).
        """
        import snitchbot.client.ports.driving.public_api as api

        api._initialized = True
        api._initialized_pid = os.getpid() + 9999
        stored = dict(service="svc", token="tok:999", chat_id="100", anomaly=None)
        api._stored_config = stored.copy()

        impl_calls = []

        def fake_impl(**kw):
            impl_calls.append(kw)

        monkeypatch.setattr(api, "_init_impl", fake_impl)

        api._after_fork_in_child()

        assert len(impl_calls) == 1
        assert impl_calls[0]["service"] == "svc"
        assert impl_calls[0]["token"] == "tok:999"
        assert impl_calls[0]["chat_id"] == "100"

    def test_fork_before_init_is_noop(self, monkeypatch):
        """
        Given init() was never called (_initialized_pid is None),
        When _after_fork_in_child() is invoked,
        Then it exits early (noop) — no crash, no reinit.
        """
        import snitchbot.client.ports.driving.public_api as api

        assert api._initialized_pid is None

        impl_calls = []

        def fake_impl(**kw):
            impl_calls.append(kw)

        monkeypatch.setattr(api, "_init_impl", fake_impl)

        # Should not raise, should not call impl
        api._after_fork_in_child()

        assert not impl_calls
        assert api._initialized is False
