"""Tests for sys.excepthook driving adapter.

CI1: wraps previous hook and always calls it
CI2: exceptions inside hook are swallowed (never raise out)
CI3: sys.excepthook emits lifecycle shutdown reason="crash"
I9: hook errors never propagate to host app
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

from snitchbot.client.adapters.driving.excepthooks import sys_excepthook


@pytest.fixture(autouse=True)
def restore_excepthook():
    """Restore sys.excepthook after each test."""
    original = sys.excepthook
    yield
    sys.excepthook = original
    sys_excepthook._original_excepthook = None


def _make_deps(**overrides):
    defaults = dict(
        send_event=MagicMock(),
        classify_severity=MagicMock(return_value="error"),
        extract_stack=MagicMock(return_value=[]),
        build_shutdown=MagicMock(return_value={"kind": "lifecycle", "reason": "crash"}),
    )
    defaults.update(overrides)
    return defaults


def _make_exc():
    try:
        raise RuntimeError("test error")
    except RuntimeError:
        return sys.exc_info()


class TestSysExcepthookInstall:
    def test_wraps_previous_and_calls_it(self):
        """
        Given a custom sys.excepthook already installed,
        When our hook is installed and triggered,
        Then the previous hook is called exactly once with the same args.  # CI1
        """
        previous = MagicMock()
        sys.excepthook = previous
        deps = _make_deps()

        sys_excepthook.install(**deps)

        exc_type, exc_value, exc_tb = _make_exc()
        sys.excepthook(exc_type, exc_value, exc_tb)

        previous.assert_called_once_with(exc_type, exc_value, exc_tb)

    def test_emits_crash_event_with_origin_sys_excepthook(self):
        """
        Given installed sys_excepthook,
        When an unhandled exception occurs,
        Then send_event is called with origin="sys_excepthook".
        """
        deps = _make_deps()
        sys_excepthook.install(**deps)

        exc_type, exc_value, exc_tb = _make_exc()
        sys.excepthook(exc_type, exc_value, exc_tb)

        assert deps["send_event"].call_count >= 1
        first_call_arg = deps["send_event"].call_args_list[0][0][0]
        assert first_call_arg["payload"]["origin"] == "sys_excepthook"

    def test_emits_lifecycle_shutdown_reason_crash(self):
        """
        Given installed sys_excepthook with build_shutdown returning a shutdown event,
        When the hook is triggered,
        Then send_event is called with the shutdown event (CI3).
        """
        shutdown_event = {"kind": "lifecycle", "reason": "crash"}
        deps = _make_deps(build_shutdown=MagicMock(return_value=shutdown_event))
        sys_excepthook.install(**deps)

        exc_type, exc_value, exc_tb = _make_exc()
        sys.excepthook(exc_type, exc_value, exc_tb)

        deps["build_shutdown"].assert_called_once_with(reason="crash")
        # send_event should be called with the shutdown event
        calls = [call[0][0] for call in deps["send_event"].call_args_list]
        assert shutdown_event in calls

    def test_exception_inside_hook_swallowed(self):
        """
        Given send_event raises an exception,
        When the hook fires,
        Then the exception is NOT propagated (CI2, I9).
        """
        deps = _make_deps(send_event=MagicMock(side_effect=RuntimeError("boom")))
        sys_excepthook.install(**deps)

        exc_type, exc_value, exc_tb = _make_exc()
        # Must not raise
        sys.excepthook(exc_type, exc_value, exc_tb)

    def test_original_hook_called_even_on_our_failure(self):
        """
        Given send_event raises,
        When the hook fires,
        Then the original hook is STILL called (CI1 is not bypassed by CI2).
        """
        previous = MagicMock()
        sys.excepthook = previous
        deps = _make_deps(send_event=MagicMock(side_effect=RuntimeError("boom")))
        sys_excepthook.install(**deps)

        exc_type, exc_value, exc_tb = _make_exc()
        sys.excepthook(exc_type, exc_value, exc_tb)

        previous.assert_called_once_with(exc_type, exc_value, exc_tb)

    def test_uninstall_restores_original(self):
        """
        Given sys_excepthook installed,
        When uninstall() is called,
        Then sys.excepthook is restored to what it was before install().
        """
        original = MagicMock()
        sys.excepthook = original
        deps = _make_deps()

        sys_excepthook.install(**deps)
        assert sys.excepthook is not original

        sys_excepthook.uninstall()
        assert sys.excepthook is original

    def test_classify_severity_called_with_exc_type(self):
        """
        Given installed hook,
        When triggered,
        Then classify_severity is called with the exception type.
        """
        deps = _make_deps()
        sys_excepthook.install(**deps)

        exc_type, exc_value, exc_tb = _make_exc()
        sys.excepthook(exc_type, exc_value, exc_tb)

        deps["classify_severity"].assert_called_once_with(exc_type)

    def test_extract_stack_called_with_traceback(self):
        """
        Given installed hook,
        When triggered,
        Then extract_stack is called with the traceback.
        """
        deps = _make_deps()
        sys_excepthook.install(**deps)

        exc_type, exc_value, exc_tb = _make_exc()
        sys.excepthook(exc_type, exc_value, exc_tb)

        deps["extract_stack"].assert_called_once_with(exc_tb)

    def test_no_shutdown_if_build_shutdown_returns_none(self):
        """
        Given build_shutdown returns None (already sent),
        When hook fires,
        Then send_event is called only once (for the crash event, not shutdown).
        """
        deps = _make_deps(build_shutdown=MagicMock(return_value=None))
        sys_excepthook.install(**deps)

        exc_type, exc_value, exc_tb = _make_exc()
        sys.excepthook(exc_type, exc_value, exc_tb)

        # Only crash event sent, no shutdown event
        assert deps["send_event"].call_count == 1
