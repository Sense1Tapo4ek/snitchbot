"""Tests for asyncio lazy-bind exception handler (Task 4.5).

CI4: asyncio exception handler installed via lazy-bind from pinger's first tick.
CI5: instrument_loop idempotent via sentinel attribute.
CI36: asyncio handler does NOT emit lifecycle/shutdown event.
I9: handler swallows own errors.
"""
import asyncio
import asyncio.events
from unittest.mock import MagicMock, call

import pytest

from snitchbot.client.adapters.driving.excepthooks import asyncio_patch


def _make_deps(**overrides):
    defaults = dict(
        send_event=MagicMock(),
        classify_severity=MagicMock(return_value="error"),
        extract_stack=MagicMock(return_value=[]),
    )
    defaults.update(overrides)
    return defaults


@pytest.fixture(autouse=True)
def restore_asyncio_patch():
    """Restore asyncio.new_event_loop and asyncio.events.new_event_loop after each test."""
    original_events = asyncio.events.new_event_loop
    original_asyncio = asyncio.new_event_loop
    original_module_state = asyncio_patch._original_new_event_loop
    yield
    asyncio.events.new_event_loop = original_events
    asyncio.new_event_loop = original_asyncio
    asyncio_patch._original_new_event_loop = original_module_state


class TestMonkeyPatch:
    def test_monkey_patch_affects_new_event_loop(self):
        """
        Given asyncio_patch.install() called,
        When asyncio.new_event_loop() is called,
        Then the returned loop has the sentinel attribute set (instrumented).
        """
        deps = _make_deps()
        asyncio_patch.install(**deps)

        loop = asyncio.new_event_loop()
        try:
            assert getattr(loop, asyncio_patch._INSTRUMENT_SENTINEL, False) is True
        finally:
            loop.close()

    def test_uninstall_restores_original(self):
        """
        Given asyncio_patch.install() called,
        When asyncio_patch.uninstall() is called,
        Then asyncio.events.new_event_loop is restored to original.
        """
        original = asyncio.events.new_event_loop
        deps = _make_deps()

        asyncio_patch.install(**deps)
        assert asyncio.events.new_event_loop is not original

        asyncio_patch.uninstall()
        assert asyncio.events.new_event_loop is original

    def test_uninstall_clears_module_state(self):
        """
        Given install() then uninstall(),
        When uninstall() is called,
        Then _original_new_event_loop is None.
        """
        deps = _make_deps()
        asyncio_patch.install(**deps)
        asyncio_patch.uninstall()
        assert asyncio_patch._original_new_event_loop is None


class TestPingerInstallsHandler:
    def test_pinger_installs_exception_handler(self):
        """
        Given a newly created loop (via patched new_event_loop),
        When the loop runs one iteration (pinger fires),
        Then the loop has a custom exception handler installed (CI4).
        """
        deps = _make_deps()
        asyncio_patch.install(**deps)

        loop = asyncio.new_event_loop()
        try:
            # Run briefly to let call_soon fire
            loop.run_until_complete(asyncio.sleep(0))
            handler = loop.get_exception_handler()
            assert handler is not None, "Exception handler must be set after pinger tick"
        finally:
            loop.close()

    def test_handler_emits_crash_with_origin_asyncio_handler(self):
        """
        Given a loop with installed handler,
        When an unhandled exception occurs in a task,
        Then send_event is called with kind='crash' and origin='asyncio_handler' (CI4).
        """
        deps = _make_deps()
        asyncio_patch.install(**deps)

        async def failing_task():
            raise RuntimeError("async kaboom")

        loop = asyncio.new_event_loop()
        try:
            # Run pinger first tick to install handler
            loop.run_until_complete(asyncio.sleep(0))

            # Simulate exception handler call
            exc = RuntimeError("async kaboom")
            context = {"exception": exc, "message": "Task exception was never retrieved"}
            loop.call_exception_handler(context)

            deps["send_event"].assert_called_once()
            event = deps["send_event"].call_args[0][0]
            assert event["kind"] == "crash"
            assert event["payload"]["origin"] == "asyncio_handler"
        finally:
            loop.close()

    def test_handler_does_not_emit_lifecycle_shutdown(self):
        """
        Given asyncio exception handler installed,
        When an exception occurs in a task,
        Then NO lifecycle/shutdown event is sent (CI36).
        """
        deps = _make_deps()
        asyncio_patch.install(**deps)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.sleep(0))

            exc = RuntimeError("async error")
            context = {"exception": exc, "message": "Task exception"}
            loop.call_exception_handler(context)

            assert deps["send_event"].call_count == 1
            event = deps["send_event"].call_args[0][0]
            assert event.get("kind") != "lifecycle"
        finally:
            loop.close()

    def test_handler_calls_default_after(self):
        """
        Given asyncio exception handler installed,
        When an exception occurs,
        Then loop.default_exception_handler is still called (chain, CI1-equivalent).
        """
        deps = _make_deps()
        asyncio_patch.install(**deps)

        loop = asyncio.new_event_loop()
        original_default = loop.default_exception_handler
        default_calls = []

        def tracking_default(ctx):
            default_calls.append(ctx)

        loop.default_exception_handler = tracking_default

        try:
            loop.run_until_complete(asyncio.sleep(0))

            exc = RuntimeError("check chaining")
            context = {"exception": exc, "message": "test"}
            loop.call_exception_handler(context)

            assert len(default_calls) == 1
            assert default_calls[0] is context
        finally:
            loop.close()

    def test_handler_swallows_own_errors(self):
        """
        Given send_event raises internally,
        When exception handler fires,
        Then the error is swallowed and not propagated (I9).
        """
        exploding_send = MagicMock(side_effect=RuntimeError("send failed"))
        deps = _make_deps(send_event=exploding_send)
        asyncio_patch.install(**deps)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.sleep(0))

            exc = RuntimeError("task error")
            context = {"exception": exc, "message": "test"}
            # Must not raise
            loop.call_exception_handler(context)
        finally:
            loop.close()

    def test_handler_with_no_exception_in_context(self):
        """
        Given asyncio exception handler installed,
        When context has no 'exception' key (e.g., pure message context),
        Then send_event is NOT called.
        """
        deps = _make_deps()
        asyncio_patch.install(**deps)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.sleep(0))

            context = {"message": "Some asyncio internal warning"}
            loop.call_exception_handler(context)

            deps["send_event"].assert_not_called()
        finally:
            loop.close()


class TestInstrumentLoop:
    def test_instrument_loop_on_existing_loop(self):
        """
        Given an existing (not-yet-running) loop,
        When instrument_loop() is called,
        Then the sentinel is set and handler is installed after one iteration (CI5).
        """
        deps = _make_deps()
        loop = asyncio.new_event_loop()
        try:
            asyncio_patch.instrument_loop(loop, **deps)
            assert getattr(loop, asyncio_patch._INSTRUMENT_SENTINEL, False) is True

            loop.run_until_complete(asyncio.sleep(0))
            assert loop.get_exception_handler() is not None
        finally:
            loop.close()

    def test_instrument_loop_idempotent(self):
        """
        Given instrument_loop() called twice on the same loop,
        When the loop runs,
        Then only ONE handler is installed (no double-wrapping) (CI5).
        """
        deps = _make_deps()
        loop = asyncio.new_event_loop()
        try:
            asyncio_patch.instrument_loop(loop, **deps)
            asyncio_patch.instrument_loop(loop, **deps)  # second call — no-op

            loop.run_until_complete(asyncio.sleep(0))

            # Fire the handler once — should be called exactly once per exception
            exc = RuntimeError("idempotent test")
            context = {"exception": exc, "message": "test"}
            loop.call_exception_handler(context)

            # send_event called once (not twice from double-instrumentation)
            assert deps["send_event"].call_count == 1
        finally:
            loop.close()

    def test_instrument_loop_on_running_loop(self):
        """
        Given a currently running loop,
        When instrument_loop() is called from a thread or via call_soon_threadsafe,
        Then the loop gets instrumented without error (CI5).
        """
        deps = _make_deps()
        results = {}

        async def check():
            loop = asyncio.get_running_loop()
            # Instrument the running loop via the public helper
            asyncio_patch.instrument_loop(loop, **deps)
            assert getattr(loop, asyncio_patch._INSTRUMENT_SENTINEL, False) is True
            results["instrumented"] = True
            # Allow pinger to fire
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            results["handler_set"] = loop.get_exception_handler() is not None

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(check())
            assert results.get("instrumented") is True
            assert results.get("handler_set") is True
        finally:
            loop.close()

    def test_uvloop_compat_smoke(self):
        """
        Given a custom loop subclass (simulating uvloop),
        When instrument_loop() is called,
        Then it works correctly without requiring asyncio.new_event_loop path.
        """
        class CustomLoop(asyncio.SelectorEventLoop):
            """Simulates a uvloop-style custom event loop."""
            pass

        deps = _make_deps()
        loop = CustomLoop()
        try:
            asyncio_patch.instrument_loop(loop, **deps)
            assert getattr(loop, asyncio_patch._INSTRUMENT_SENTINEL, False) is True

            loop.run_until_complete(asyncio.sleep(0))
            assert loop.get_exception_handler() is not None
        finally:
            loop.close()


class TestCrashEventFields:
    def test_crash_event_has_required_fields(self):
        """
        Given asyncio exception handler installed,
        When an exception fires through the handler,
        Then crash event has kind, severity, origin, exception_type, message fields.
        """
        deps = _make_deps()
        asyncio_patch.install(**deps)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.sleep(0))

            exc = ValueError("field check")
            context = {"exception": exc, "message": "test"}
            loop.call_exception_handler(context)

            event = deps["send_event"].call_args[0][0]
            assert event["kind"] == "crash"
            assert event["payload"]["origin"] == "asyncio_handler"
            assert "severity" in event
            assert event["payload"]["exception_type"] == "ValueError"
            assert "message" in event["payload"]
        finally:
            loop.close()

    def test_classify_severity_called_with_exc_type(self):
        """
        Given asyncio exception handler installed,
        When an exception fires,
        Then classify_severity is called with the exception type.
        """
        deps = _make_deps(classify_severity=MagicMock(return_value="critical"))
        asyncio_patch.install(**deps)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.sleep(0))

            exc = RuntimeError("test")
            context = {"exception": exc, "message": "test"}
            loop.call_exception_handler(context)

            deps["classify_severity"].assert_called_once_with(RuntimeError)
            event = deps["send_event"].call_args[0][0]
            assert event["severity"] == "critical"
        finally:
            loop.close()

    def test_extract_stack_called_with_traceback(self):
        """
        Given asyncio exception handler installed,
        When an exception with traceback fires,
        Then extract_stack is called with the traceback.
        """
        extract_mock = MagicMock(return_value=[{"file": "test.py", "line": 1}])
        deps = _make_deps(extract_stack=extract_mock)
        asyncio_patch.install(**deps)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(asyncio.sleep(0))

            try:
                raise RuntimeError("with tb")
            except RuntimeError as e:
                exc = e

            context = {"exception": exc, "message": "test"}
            loop.call_exception_handler(context)

            extract_mock.assert_called_once_with(exc.__traceback__)
            event = deps["send_event"].call_args[0][0]
            assert event["payload"]["stack"] == [{"file": "test.py", "line": 1}]
        finally:
            loop.close()
