"""Tests for atexit hook driving adapter.

CI34: emits lifecycle shutdown reason="clean_exit"
CI18: skipped if build_shutdown returns None (already sent)
"""
import atexit
from unittest.mock import MagicMock, patch

import pytest

from snitchbot.client.adapters.driving import atexit_hook


def _make_deps(**overrides):
    defaults = dict(
        send_event=MagicMock(),
        build_shutdown=MagicMock(return_value={"kind": "lifecycle", "reason": "clean_exit"}),
    )
    defaults.update(overrides)
    return defaults


class TestAtexitHook:
    def test_clean_exit_emits_lifecycle_shutdown(self):
        """
        Given atexit_hook installed,
        When the process exits cleanly,
        Then send_event is called with reason="clean_exit" (CI34).
        """
        deps = _make_deps()
        captured_callbacks = []

        with patch.object(atexit_hook.atexit, "register", side_effect=captured_callbacks.append):
            atexit_hook.install(**deps)

        assert len(captured_callbacks) == 1
        # Simulate atexit firing
        captured_callbacks[0]()

        deps["build_shutdown"].assert_called_once_with(reason="clean_exit")
        deps["send_event"].assert_called_once()
        event = deps["send_event"].call_args[0][0]
        assert event.get("reason") == "clean_exit"

    def test_skipped_if_already_sent(self):
        """
        Given build_shutdown returns None (CI18 - already sent by signal handler),
        When atexit callback fires,
        Then send_event is NOT called.
        """
        deps = _make_deps(build_shutdown=MagicMock(return_value=None))
        captured_callbacks = []

        with patch.object(atexit_hook.atexit, "register", side_effect=captured_callbacks.append):
            atexit_hook.install(**deps)

        captured_callbacks[0]()
        deps["send_event"].assert_not_called()

    def test_exception_in_send_swallowed(self):
        """
        Given send_event raises an exception,
        When atexit callback fires,
        Then the exception is swallowed (must not propagate).
        """
        deps = _make_deps(send_event=MagicMock(side_effect=RuntimeError("send failed")))
        captured_callbacks = []

        with patch.object(atexit_hook.atexit, "register", side_effect=captured_callbacks.append):
            atexit_hook.install(**deps)

        # Must not raise
        captured_callbacks[0]()

    def test_install_registers_with_atexit(self):
        """
        Given install() is called,
        When checking atexit registrations,
        Then atexit.register was called once.
        """
        deps = _make_deps()

        with patch.object(atexit_hook.atexit, "register") as mock_register:
            atexit_hook.install(**deps)

        mock_register.assert_called_once()

    def test_exception_in_build_shutdown_swallowed(self):
        """
        Given build_shutdown raises an exception,
        When atexit callback fires,
        Then no exception propagates.
        """
        deps = _make_deps(build_shutdown=MagicMock(side_effect=RuntimeError("build failed")))
        captured_callbacks = []

        with patch.object(atexit_hook.atexit, "register", side_effect=captured_callbacks.append):
            atexit_hook.install(**deps)

        # Must not raise
        captured_callbacks[0]()
        deps["send_event"].assert_not_called()
