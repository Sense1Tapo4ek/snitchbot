"""Tests for signal handlers driving adapter.

CI16: handlers only installed from main thread
CI17: SIGTERM emits lifecycle shutdown reason="sigterm"
CI18: _sent_shutdown_event deduplication (via build_shutdown returning None)
CI19: SIGHUP not installed
"""
import signal
import threading
from unittest.mock import MagicMock, patch, call

import pytest

from snitchbot.client.adapters.driving.signals import signal_handlers


@pytest.fixture(autouse=True)
def reset_module_state():
    """Reset module state before/after each test."""
    signal_handlers._previous_sigterm = None
    signal_handlers._previous_sigint = None
    yield
    signal_handlers._previous_sigterm = None
    signal_handlers._previous_sigint = None


def _make_deps(**overrides):
    defaults = dict(
        send_event=MagicMock(),
        build_shutdown=MagicMock(return_value={"kind": "lifecycle", "reason": "sigterm"}),
    )
    defaults.update(overrides)
    return defaults


class TestSignalHandlerInstall:
    def test_sigterm_emits_lifecycle_shutdown_reason_sigterm(self):
        """
        Given signal_handlers installed,
        When SIGTERM handler is triggered,
        Then build_shutdown is called with reason="sigterm" and the event is sent (CI17).
        """
        deps = _make_deps(
            build_shutdown=MagicMock(return_value={"kind": "lifecycle", "reason": "sigterm"})
        )

        captured_handlers = {}

        def mock_signal(signum, handler):
            captured_handlers[signum] = handler
            return signal.SIG_DFL

        with patch.object(signal_handlers.signal, "signal", side_effect=mock_signal):
            signal_handlers.install(**deps)

        assert signal.SIGTERM in captured_handlers
        # Patch os.kill + signal.signal to prevent actual process kill (SIG_DFL chain)
        with patch.object(signal_handlers.signal, "signal"), \
             patch.object(signal_handlers.os, "kill"):
            captured_handlers[signal.SIGTERM](signal.SIGTERM, None)

        deps["build_shutdown"].assert_called_with(reason="sigterm")
        assert deps["send_event"].call_count >= 1
        sent_events = [c[0][0] for c in deps["send_event"].call_args_list]
        assert any(e.get("reason") == "sigterm" for e in sent_events)

    def test_sigint_emits_lifecycle_shutdown(self):
        """
        Given signal_handlers installed,
        When SIGINT handler is triggered,
        Then build_shutdown is called with reason="sigint" and event sent.
        """
        shutdown_event = {"kind": "lifecycle", "reason": "sigint"}
        deps = _make_deps(build_shutdown=MagicMock(return_value=shutdown_event))

        captured_handlers = {}

        def mock_signal(signum, handler):
            captured_handlers[signum] = handler
            return signal.SIG_DFL

        with patch.object(signal_handlers.signal, "signal", side_effect=mock_signal):
            signal_handlers.install(**deps)

        assert signal.SIGINT in captured_handlers
        with patch.object(signal_handlers.signal, "signal"), \
             patch.object(signal_handlers.os, "kill"):
            captured_handlers[signal.SIGINT](signal.SIGINT, None)

        deps["build_shutdown"].assert_called_with(reason="sigint")

    def test_chains_to_previous_callable(self):
        """
        Given previous SIGTERM handler is a callable,
        When our handler fires,
        Then the previous callable is invoked.
        """
        previous_handler = MagicMock()
        deps = _make_deps()

        captured_handlers = {}

        def mock_signal(signum, handler):
            captured_handlers[signum] = handler
            return previous_handler  # return previous as callable

        with patch.object(signal_handlers.signal, "signal", side_effect=mock_signal):
            signal_handlers.install(**deps)

        captured_handlers[signal.SIGTERM](signal.SIGTERM, None)
        previous_handler.assert_called_once_with(signal.SIGTERM, None)

    def test_chains_to_SIG_DFL_by_reraise(self):
        """
        Given previous SIGTERM handler is SIG_DFL,
        When our handler fires,
        Then it resets the signal to SIG_DFL and re-raises (kills process via os.kill).
        """
        deps = _make_deps()
        captured_handlers = {}

        def mock_signal(signum, handler):
            captured_handlers[signum] = handler
            return signal.SIG_DFL  # previous is SIG_DFL

        with patch.object(signal_handlers.signal, "signal", side_effect=mock_signal):
            signal_handlers.install(**deps)

        # Patch os.kill to avoid actually killing process + signal.signal for reset
        import os as _os
        expected_pid = _os.getpid()
        with patch.object(signal_handlers.signal, "signal"), \
             patch.object(signal_handlers.os, "kill") as mock_kill:
            captured_handlers[signal.SIGTERM](signal.SIGTERM, None)
            mock_kill.assert_called_once_with(expected_pid, signal.SIGTERM)

    def test_skipped_when_not_main_thread(self):
        """
        Given install() is called from a non-main thread,
        When signal.signal raises ValueError,
        Then no exception propagates (CI16).
        """
        deps = _make_deps()
        errors = []

        def run_from_thread():
            try:
                # Force ValueError by patching signal.signal
                with patch.object(
                    signal_handlers.signal, "signal",
                    side_effect=ValueError("signal only works in main thread")
                ):
                    signal_handlers.install(**deps)
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=run_from_thread)
        t.start()
        t.join()

        assert errors == [], f"Expected no exceptions but got: {errors}"

    def test_sighup_not_installed(self):
        """
        Given signal_handlers installed,
        When checking registered signals,
        Then SIGHUP is NOT among them (CI19).
        """
        deps = _make_deps()
        captured_sigs = []

        def mock_signal(signum, handler):
            captured_sigs.append(signum)
            return signal.SIG_DFL

        with patch.object(signal_handlers.signal, "signal", side_effect=mock_signal):
            signal_handlers.install(**deps)

        assert signal.SIGHUP not in captured_sigs

    def test_uninstall_restores_originals(self):
        """
        Given signal_handlers installed (with mocked signal.signal),
        When uninstall() is called,
        Then signal.signal is called to restore previous handlers.
        """
        deps = _make_deps()
        prev_term = MagicMock()
        prev_int = MagicMock()

        call_count = [0]

        def mock_signal(signum, handler):
            call_count[0] += 1
            if signum == signal.SIGTERM:
                return prev_term
            if signum == signal.SIGINT:
                return prev_int
            return signal.SIG_DFL

        with patch.object(signal_handlers.signal, "signal", side_effect=mock_signal):
            signal_handlers.install(**deps)

        # Now uninstall
        with patch.object(signal_handlers.signal, "signal") as mock_restore:
            signal_handlers.uninstall()
            restore_calls = {c[0][0]: c[0][1] for c in mock_restore.call_args_list}
            assert restore_calls.get(signal.SIGTERM) is prev_term
            assert restore_calls.get(signal.SIGINT) is prev_int

    def test_sigint_does_not_cause_double_alert_with_crash_path(self):
        """CI7: if SIGINT handler sends lifecycle/shutdown, the atexit path
        should not send a second one (build_shutdown returns None)."""
        calls = []

        def build_shutdown(reason, exit_code=None):
            if calls:
                return None
            calls.append(reason)
            return {"kind": "lifecycle", "reason": reason}

        send_event = MagicMock()
        deps = dict(send_event=send_event, build_shutdown=build_shutdown)

        captured_handlers = {}

        def mock_signal(signum, handler):
            captured_handlers[signum] = handler
            return signal.SIG_DFL

        with patch.object(signal_handlers.signal, "signal", side_effect=mock_signal):
            signal_handlers.install(**deps)

        # Simulate SIGINT -> build_shutdown called -> returns event -> send_event called
        with patch.object(signal_handlers.signal, "signal"), \
             patch.object(signal_handlers.os, "kill"):
            captured_handlers[signal.SIGINT](signal.SIGINT, None)

        assert len(calls) == 1
        assert send_event.call_count == 1

        # Simulate atexit path -> build_shutdown called again -> returns None -> no send
        result = build_shutdown(reason="atexit")
        assert result is None
        assert send_event.call_count == 1  # unchanged

    def test_build_shutdown_returns_none_no_send(self):
        """
        Given build_shutdown returns None (already sent - CI18),
        When signal handler fires,
        Then send_event is NOT called.
        """
        deps = _make_deps(build_shutdown=MagicMock(return_value=None))
        captured_handlers = {}

        def mock_signal(signum, handler):
            captured_handlers[signum] = handler
            return signal.SIG_DFL

        with patch.object(signal_handlers.signal, "signal", side_effect=mock_signal):
            with patch.object(signal_handlers.os, "kill"):
                signal_handlers.install(**deps)
                captured_handlers[signal.SIGTERM](signal.SIGTERM, None)

        deps["send_event"].assert_not_called()
