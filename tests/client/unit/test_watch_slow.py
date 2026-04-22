"""Tests for watch_slow decorator.

CI21: @watch_slow(1000) raises ValueError (positional not allowed)
CI21: detects async via asyncio.iscoroutinefunction
CI22: uses time.monotonic, not wall clock
CI23: sends event on completion even if function raises
CI24: functools.wraps preserves metadata
CI25: fast path — no event if duration < threshold
CI26: qualname captured at decoration time, not call time
"""
import asyncio
import time
from unittest.mock import MagicMock, call, patch

import pytest

from snitchbot.client.adapters.driving.instrumentation.watch_slow import watch_slow


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_send() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# 5.1.1  keyword enforcement
# ---------------------------------------------------------------------------


class TestWatchSlowValidation:
    def test_requires_keyword_threshold_ms_not_positional(self):
        """
        Given watch_slow called with positional argument,
        When decorator factory is invoked as @watch_slow(1000),
        Then ValueError is raised (CI21).
        """
        with pytest.raises((ValueError, TypeError)):
            watch_slow(1000)  # type: ignore[call-arg]

    def test_raises_on_zero_threshold(self):
        """
        Given threshold_ms=0,
        When watch_slow factory is called,
        Then ValueError is raised.
        """
        with pytest.raises(ValueError):
            watch_slow(threshold_ms=0)

    def test_raises_on_negative_threshold(self):
        """
        Given threshold_ms=-1,
        When watch_slow factory is called,
        Then ValueError is raised.
        """
        with pytest.raises(ValueError):
            watch_slow(threshold_ms=-1)

    def test_raises_on_float_threshold(self):
        """
        Given threshold_ms=1.5 (float instead of int),
        When watch_slow factory is called,
        Then ValueError is raised.
        """
        with pytest.raises(ValueError):
            watch_slow(threshold_ms=1.5)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 5.1.2  sync fast path (CI25)
# ---------------------------------------------------------------------------


class TestSyncFastPath:
    def test_sync_function_fast_path_no_event_sent(self):
        """
        Given a sync function that runs faster than threshold_ms,
        When the wrapped function is called,
        Then no event is sent (CI25).
        """
        send = _make_send()

        @watch_slow(threshold_ms=10_000, send_event=send)
        def fast():
            return 42

        result = fast()
        assert result == 42
        send.assert_not_called()


# ---------------------------------------------------------------------------
# 5.1.3  sync slow path (CI23)
# ---------------------------------------------------------------------------


class TestSyncSlowPath:
    def test_sync_function_slow_sends_slow_call_event(self):
        """
        Given a sync function that runs slower than threshold_ms,
        When the wrapped function is called,
        Then a slow_call event is sent (CI23).
        """
        send = _make_send()

        @watch_slow(threshold_ms=1, send_event=send)
        def slow():
            time.sleep(0.01)
            return "done"

        result = slow()
        assert result == "done"
        send.assert_called_once()
        event = send.call_args[0][0]
        assert event["kind"] == "slow_call"

    def test_exception_in_wrapped_function_still_sends_slow_event_and_reraises(self):
        """
        Given a sync function that raises after exceeding threshold,
        When the wrapped function is called,
        Then event is sent AND exception is re-raised (CI23).
        """
        send = _make_send()

        @watch_slow(threshold_ms=1, send_event=send)
        def boom():
            time.sleep(0.01)
            raise ValueError("kaboom")

        with pytest.raises(ValueError, match="kaboom"):
            boom()

        send.assert_called_once()

    def test_fast_function_exception_no_event_sent(self):
        """
        Given a sync function that raises quickly (below threshold),
        When the wrapped function raises,
        Then no slow_call event is sent.
        """
        send = _make_send()

        @watch_slow(threshold_ms=10_000, send_event=send)
        def quick_boom():
            raise RuntimeError("fast fail")

        with pytest.raises(RuntimeError):
            quick_boom()

        send.assert_not_called()


# ---------------------------------------------------------------------------
# 5.1.4  async detection (CI21)
# ---------------------------------------------------------------------------


class TestAsyncDetection:
    def test_async_function_detected_via_iscoroutinefunction(self):
        """
        Given an async function,
        When watch_slow wraps it,
        Then the wrapper is also a coroutine function (CI21).
        """
        @watch_slow(threshold_ms=10_000, send_event=_make_send())
        async def coro():
            return 1

        assert asyncio.iscoroutinefunction(coro)

    def test_sync_function_wrapper_is_not_coroutine(self):
        """
        Given a sync function,
        When watch_slow wraps it,
        Then the wrapper is NOT a coroutine function.
        """
        @watch_slow(threshold_ms=10_000, send_event=_make_send())
        def fn():
            return 1

        assert not asyncio.iscoroutinefunction(fn)

    @pytest.mark.asyncio
    async def test_async_function_slow_sends_event_on_completion(self):
        """
        Given an async function that runs slower than threshold,
        When it is awaited,
        Then a slow_call event is sent.
        """
        send = _make_send()

        @watch_slow(threshold_ms=1, send_event=send)
        async def slow_coro():
            await asyncio.sleep(0.01)
            return "ok"

        result = await slow_coro()
        assert result == "ok"
        send.assert_called_once()
        event = send.call_args[0][0]
        assert event["kind"] == "slow_call"

    @pytest.mark.asyncio
    async def test_async_exception_slow_sends_event_and_reraises(self):
        """
        Given an async function that raises after exceeding threshold,
        When awaited,
        Then event is sent AND exception propagates (CI23).
        """
        send = _make_send()

        @watch_slow(threshold_ms=1, send_event=send)
        async def coro_boom():
            await asyncio.sleep(0.01)
            raise TypeError("async kaboom")

        with pytest.raises(TypeError, match="async kaboom"):
            await coro_boom()

        send.assert_called_once()


# ---------------------------------------------------------------------------
# 5.1.5  functools.wraps (CI24)
# ---------------------------------------------------------------------------


class TestFunctoolsWraps:
    def test_functools_wraps_preserves_metadata(self):
        """
        Given a named function with docstring,
        When watch_slow wraps it,
        Then __name__, __qualname__, __doc__ are preserved (CI24).
        """
        @watch_slow(threshold_ms=1000, send_event=_make_send())
        def my_func():
            """My docstring."""

        assert my_func.__name__ == "my_func"
        assert "my_func" in my_func.__qualname__
        assert my_func.__doc__ == "My docstring."


# ---------------------------------------------------------------------------
# 5.1.6  qualname at decoration time (CI26)
# ---------------------------------------------------------------------------


class TestQualnameCapturedAtDecorationTime:
    def test_qualname_computed_at_decoration_time_once(self):
        """
        Given a function decorated with watch_slow,
        When the function is called multiple times,
        Then the same qualname is used in all events (CI26 — no per-call recompute).
        """
        send = _make_send()

        @watch_slow(threshold_ms=1, send_event=send)
        def my_fn():
            time.sleep(0.01)

        my_fn()
        my_fn()

        assert send.call_count == 2
        calls_qualnames = [c[0][0]["payload"]["func_qualname"] for c in send.call_args_list]
        assert calls_qualnames[0] == calls_qualnames[1]
        assert "my_fn" in calls_qualnames[0]


# ---------------------------------------------------------------------------
# 5.1.7  time.monotonic (CI22)
# ---------------------------------------------------------------------------


class TestMonotonicClock:
    def test_duration_uses_time_monotonic_not_wall_clock(self):
        """
        Given time.monotonic is patched to return controlled values,
        When a function is called,
        Then duration_ms in event matches monotonic delta, not wall time (CI22).
        """
        send = _make_send()
        times = iter([0.0, 2.0])  # start=0, end=2 -> 2000 ms

        @watch_slow(threshold_ms=1000, send_event=send)
        def fn():
            return 99

        with patch("time.monotonic", side_effect=lambda: next(times)):
            result = fn()

        assert result == 99
        send.assert_called_once()
        event = send.call_args[0][0]
        assert event["payload"]["duration_ms"] == pytest.approx(2000, abs=5)


# ---------------------------------------------------------------------------
# 5.1.8  event structure
# ---------------------------------------------------------------------------


class TestEventStructure:
    def test_event_has_kind_slow_call_severity_warning(self):
        """
        Given a slow function,
        When event is emitted,
        Then kind="slow_call" and severity="warning".
        """
        send = _make_send()

        @watch_slow(threshold_ms=1, send_event=send)
        def fn():
            time.sleep(0.01)

        fn()
        event = send.call_args[0][0]
        assert event["kind"] == "slow_call"
        assert event["severity"] == "warning"

    def test_location_file_and_line_captured(self):
        """
        Given a decorated function,
        When a slow event is emitted,
        Then payload.location has file and line fields.
        """
        send = _make_send()

        @watch_slow(threshold_ms=1, send_event=send)
        def fn():
            time.sleep(0.01)

        fn()
        payload = send.call_args[0][0]["payload"]
        assert "location" in payload
        loc = payload["location"]
        assert "file" in loc
        assert "line" in loc
        assert isinstance(loc["line"], int)

    def test_is_async_flag_correct_for_sync(self):
        """
        Given a sync function,
        When event is emitted,
        Then payload.is_async is False.
        """
        send = _make_send()

        @watch_slow(threshold_ms=1, send_event=send)
        def fn():
            time.sleep(0.01)

        fn()
        payload = send.call_args[0][0]["payload"]
        assert payload["is_async"] is False

    @pytest.mark.asyncio
    async def test_is_async_flag_correct_for_async(self):
        """
        Given an async function,
        When event is emitted,
        Then payload.is_async is True.
        """
        send = _make_send()

        @watch_slow(threshold_ms=1, send_event=send)
        async def coro():
            await asyncio.sleep(0.01)

        await coro()
        payload = send.call_args[0][0]["payload"]
        assert payload["is_async"] is True

    def test_payload_threshold_ms_matches_configured_value(self):
        """
        Given threshold_ms=1 (very low to ensure trigger),
        When event is emitted,
        Then payload.threshold_ms == 1.
        """
        send = _make_send()

        @watch_slow(threshold_ms=1, send_event=send)
        def fn():
            time.sleep(0.01)

        fn()
        payload = send.call_args[0][0]["payload"]
        assert payload["threshold_ms"] == 1
