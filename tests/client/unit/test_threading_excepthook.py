"""Tests for threading.excepthook driving adapter.

CI1: wraps previous hook and always calls it
CI2: exceptions inside hook are swallowed
CI3/CI36: thread crash does NOT emit lifecycle shutdown
"""
import threading
import sys
from unittest.mock import MagicMock

import pytest

from snitchbot.client.adapters.driving.excepthooks import threading_excepthook


@pytest.fixture(autouse=True)
def restore_threading_excepthook():
    """Restore threading.excepthook after each test."""
    original = threading.excepthook
    yield
    threading.excepthook = original
    threading_excepthook._original_excepthook = None


def _make_deps(**overrides):
    defaults = dict(
        send_event=MagicMock(),
        classify_severity=MagicMock(return_value="error"),
        extract_stack=MagicMock(return_value=[]),
    )
    defaults.update(overrides)
    return defaults


def _make_thread_exc_args(exc_type=RuntimeError, thread_name="WorkerThread"):
    """Build a threading.ExceptHookArgs-like object."""
    try:
        raise exc_type("test error in thread")
    except exc_type:
        import sys as _sys
        exc_info = _sys.exc_info()

    thread = MagicMock()
    thread.name = thread_name

    # threading.ExceptHookArgs is a structseq — positional only on Python 3.10
    return threading.ExceptHookArgs((exc_info[0], exc_info[1], exc_info[2], thread))


class TestThreadingExcepthookInstall:
    def test_wraps_previous(self):
        """
        Given a custom threading.excepthook already installed,
        When our hook is installed and triggered,
        Then the previous hook is called exactly once with the same args.  # CI1
        """
        previous = MagicMock()
        threading.excepthook = previous
        deps = _make_deps()

        threading_excepthook.install(**deps)

        args = _make_thread_exc_args()
        threading.excepthook(args)

        previous.assert_called_once_with(args)

    def test_emits_crash_with_origin_threading_and_thread_name(self):
        """
        Given installed threading_excepthook,
        When a thread exception occurs,
        Then send_event is called with origin="threading_excepthook" and thread_name.
        """
        deps = _make_deps()
        threading_excepthook.install(**deps)

        args = _make_thread_exc_args(thread_name="MyWorker")
        threading.excepthook(args)

        assert deps["send_event"].call_count == 1
        event = deps["send_event"].call_args[0][0]
        assert event["payload"]["origin"] == "threading_excepthook"
        assert event["payload"]["thread"] == "MyWorker"

    def test_does_not_emit_lifecycle_shutdown(self):
        """
        Given installed threading_excepthook,
        When a thread exception occurs,
        Then NO lifecycle shutdown event is emitted (CI3, CI36).
        """
        deps = _make_deps()
        threading_excepthook.install(**deps)

        args = _make_thread_exc_args()
        threading.excepthook(args)

        # Only crash event, no lifecycle/shutdown
        assert deps["send_event"].call_count == 1
        event = deps["send_event"].call_args[0][0]
        assert event.get("kind") == "crash"

    def test_exception_inside_hook_swallowed(self):
        """
        Given send_event raises an exception,
        When the threading hook fires,
        Then the exception is NOT propagated (CI2).
        """
        deps = _make_deps(send_event=MagicMock(side_effect=RuntimeError("boom")))
        threading_excepthook.install(**deps)

        args = _make_thread_exc_args()
        # Must not raise
        threading.excepthook(args)

    def test_system_exit_in_thread_not_reported(self):
        """
        Given a SystemExit in a thread,
        When the hook fires,
        Then send_event is NOT called (Python ignores SystemExit in threads, we do too).
        """
        deps = _make_deps()
        threading_excepthook.install(**deps)

        args = _make_thread_exc_args(exc_type=SystemExit)
        threading.excepthook(args)

        deps["send_event"].assert_not_called()

    def test_thread_name_unknown_if_thread_is_none(self):
        """
        Given args.thread is None,
        When the hook fires,
        Then send_event is called with thread_name="unknown".
        """
        deps = _make_deps()
        threading_excepthook.install(**deps)

        try:
            raise RuntimeError("test")
        except RuntimeError:
            import sys as _sys
            exc_info = _sys.exc_info()

        args = threading.ExceptHookArgs((exc_info[0], exc_info[1], exc_info[2], None))
        threading.excepthook(args)

        event = deps["send_event"].call_args[0][0]
        assert event["payload"]["thread"] == "unknown"

    def test_uninstall_restores_original(self):
        """
        Given threading_excepthook installed,
        When uninstall() is called,
        Then threading.excepthook is restored.
        """
        original = MagicMock()
        threading.excepthook = original
        deps = _make_deps()

        threading_excepthook.install(**deps)
        assert threading.excepthook is not original

        threading_excepthook.uninstall()
        assert threading.excepthook is original
