"""Tests for public_api.init() integration — Task 5.4.

Invariants: P1, P2, P3, P4, P7, P8, I2, CI33.
"""
import os
import sys
import threading
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — reset global state between tests
# ---------------------------------------------------------------------------

def _reset_public_api():
    """Reset all module-level globals in public_api to pristine state."""
    import snitchbot.client.ports.driving.public_api as api

    api._initialized = False
    api._initialized_pid = None
    api._stored_config = None
    api._send_event_fn = None

    # Reset stats
    api._stats.events_sent = 0
    api._stats.dropped_buffer_full = 0
    api._stats.sidecar_unavailable = 0
    api._stats.sidecar_dead = 0
    api._stats.config_rejected = 0
    api._stats.invalid_events = 0
    api._stats.oversized = 0
    api._stats.internal_errors = 0
    api._stats.init_conflict = 0
    api._stats.called_before_init = 0
    api._stats.notify_exc_info_no_exception = 0


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    """Reset module state before each test and suppress _init_impl side-effects."""
    _reset_public_api()
    yield
    _reset_public_api()


# ---------------------------------------------------------------------------
# Task 5.4 — init() behaviour
# ---------------------------------------------------------------------------

class TestDisabledMode:
    def test_disabled_zero_setup(self, monkeypatch):
        """
        Given SNITCHBOT_DISABLED=1 env var,
        When init() is called,
        Then it returns immediately with zero setup (P4).
        """
        import snitchbot.client.ports.driving.public_api as api

        monkeypatch.setenv("SNITCHBOT_DISABLED", "1")
        init_impl_calls = []

        def fake_impl(**kw):
            init_impl_calls.append(kw)

        monkeypatch.setattr(api, "_init_impl", fake_impl)

        api.init("svc", token="tok:123", chat_id="456")

        assert not init_impl_calls
        assert not api._initialized
        assert api._stats.init_conflict == 0


class TestIdempotency:
    def test_idempotent_second_call_same_config(self, monkeypatch):
        """
        Given init() already called,
        When init() is called again with same config,
        Then second call is a no-op (P7) — _init_impl not called twice.
        """
        import snitchbot.client.ports.driving.public_api as api

        call_count = []

        def fake_impl(**kw):
            call_count.append(1)

        monkeypatch.setattr(api, "_init_impl", fake_impl)

        api.init("svc", token="tok:123", chat_id="456")
        api.init("svc", token="tok:123", chat_id="456")

        assert len(call_count) == 1
        assert api._stats.init_conflict == 0

    def test_different_config_increments_init_conflict(self, monkeypatch):
        """
        Given init() already called with one config,
        When init() is called with different config,
        Then stats.init_conflict is incremented (§3.2).
        """
        import snitchbot.client.ports.driving.public_api as api

        def fake_impl(**kw):
            pass

        monkeypatch.setattr(api, "_init_impl", fake_impl)

        api.init("svc", token="tok:111", chat_id="111")
        api.init("svc", token="tok:222", chat_id="222")

        assert api._stats.init_conflict == 1


class TestValidation:
    def test_validation_before_hooks(self, monkeypatch):
        """
        Given invalid chat_id,
        When init() is called,
        Then ValueError is raised before any hooks are installed (P8, §3.3).
        """
        import snitchbot.client.ports.driving.public_api as api

        hooks_installed = []

        def fake_impl(**kw):
            hooks_installed.append(1)

        monkeypatch.setattr(api, "_init_impl", fake_impl)

        with pytest.raises(ValueError):
            api.init("svc", token="tok:123", chat_id="not-a-number")

        assert not hooks_installed
        assert not api._initialized

    def test_validation_errors_raise(self, monkeypatch):
        """
        Given invalid args (empty service, bad token, bad chat_id),
        When init() is called,
        Then ValueError is raised (P8).
        """
        import snitchbot.client.ports.driving.public_api as api

        def fake_impl(**kw):
            pass

        monkeypatch.setattr(api, "_init_impl", fake_impl)

        # empty service
        with pytest.raises(ValueError):
            api.init("", token="tok:123", chat_id="456")

        # missing token
        with pytest.raises(ValueError):
            api.init("svc", token="", chat_id="456")

        # bad chat_id
        with pytest.raises(ValueError):
            api.init("svc", token="tok:123", chat_id="not-int")


class TestRuntimeErrors:
    def test_runtime_errors_go_degraded(self, monkeypatch):
        """
        Given _init_impl raises a RuntimeError (simulating sidecar unavailable),
        When init() is called,
        Then init() does NOT raise (I2, P8) — degraded mode.
        """
        import snitchbot.client.ports.driving.public_api as api

        def failing_impl(**kw):
            raise RuntimeError("sidecar not available")

        monkeypatch.setattr(api, "_init_impl", failing_impl)

        # Must not raise
        api.init("svc", token="tok:123", chat_id="456")

        # Stats should reflect internal error
        assert api._stats.internal_errors >= 1
        # _initialized is True despite degraded (init was attempted)
        assert api._initialized


class TestInstallOrder:
    def test_install_order_matches_spec(self, monkeypatch):
        """
        Given a normal init() call,
        When _init_impl is called,
        Then the init sequence follows spec §9 order.
        This is a high-level smoke: _init_impl is called with the right kwargs.
        """
        import snitchbot.client.ports.driving.public_api as api

        captured = {}

        def fake_impl(**kw):
            captured.update(kw)

        monkeypatch.setattr(api, "_init_impl", fake_impl)

        api.init("my-service", token="tok:999", chat_id="100")

        assert captured["service"] == "my-service"
        assert captured["token"] == "tok:999"
        assert captured["chat_id"] == "100"
        assert api._initialized is True

    def test_startup_lifecycle_last_step(self, monkeypatch):
        """
        Given init() calling _init_impl,
        When lifecycle startup is the last step (CI33),
        Then _initialized is set True after _init_impl returns.
        """
        import snitchbot.client.ports.driving.public_api as api

        initialized_during_impl = {}

        def fake_impl(**kw):
            # At this point, _initialized should NOT yet be True
            initialized_during_impl["val"] = api._initialized

        monkeypatch.setattr(api, "_init_impl", fake_impl)

        api.init("svc", token="tok:123", chat_id="456")

        assert initialized_during_impl["val"] is False
        assert api._initialized is True


class TestThreadSafety:
    def test_thread_safety_two_inits(self, monkeypatch):
        """
        Given two threads calling init() simultaneously (synchronized via barrier),
        When both race to acquire _init_lock,
        Then _init_impl is called exactly once (P2).

        M3 fix: barrier placed BEFORE calling init() so both threads enter the
        lock-contention zone at the same time. The lock ensures only one wins.
        """
        import snitchbot.client.ports.driving.public_api as api

        call_count = []
        start_barrier = threading.Barrier(2)

        def fake_impl(**kw):
            call_count.append(1)

        monkeypatch.setattr(api, "_init_impl", fake_impl)

        errors = []

        def run():
            try:
                start_barrier.wait(timeout=3)  # both threads arrive together
                api.init("svc", token="tok:123", chat_id="456")
            except threading.BrokenBarrierError:
                pass
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=run)
        t2 = threading.Thread(target=run)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)

        assert not errors, f"Thread errors: {errors}"
        assert len(call_count) == 1, f"Expected 1 init_impl call, got {len(call_count)}"


class TestCalledBeforeInit:
    def test_called_before_init_stats(self, monkeypatch):
        """
        Given init() has NOT been called,
        When notify() is called,
        Then stats.called_before_init is incremented (P3).
        """
        import snitchbot.client.ports.driving.public_api as api

        api.notify("hello before init")

        assert api._stats.called_before_init == 1


class TestNotifyNeverRaises:
    def test_notify_never_raises(self, monkeypatch):
        """
        Given init() was called (patched),
        When notify() is called,
        Then it never raises even on internal errors (P1).
        """
        import snitchbot.client.ports.driving.public_api as api

        monkeypatch.setattr(api, "_init_impl", lambda **kw: None)
        api.init("svc", token="tok:123", chat_id="456")

        # Inject a bug in the send path
        monkeypatch.setattr(api, "_send_event_fn", MagicMock(side_effect=RuntimeError("boom")))

        # Must not raise
        api.notify("test message")
