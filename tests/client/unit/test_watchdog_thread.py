"""Unit tests for WatchdogThread and pinger coroutine.

Uses mocked loop / send_event. No real threading waits > 1 s.

Invariants tested:
- CI9, CI10: detects block > threshold, fires hit
- CI11: uses Event.wait(timeout), not time.sleep; cooldown via guard-check
- CI12: snapshot via call_soon_threadsafe + Future
- CI13: snapshot timeout -> event with unavailable marker
- CI14: severity escalation
- CI15: sync app (no loop) -> noop
- event-model §4.4: stuck_tasks capped at 10
"""
import asyncio
import threading
import time
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from snitchbot.client.adapters.driving.watchdog.pinger_coroutine import (
    LastAlive,
    pinger,
)
from snitchbot.client.adapters.driving.watchdog.watchdog_thread import WatchdogThread
from snitchbot.shared.constants import (
    WATCHDOG_THRESHOLD_MS,
    WATCHDOG_COOLDOWN_SEC,
    WATCHDOG_CHECK_INTERVAL_SEC,
    WATCHDOG_ESCALATION_WINDOW_SEC,
    PINGER_INTERVAL_SEC,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_thread(
    *,
    last_alive=None,
    send_event=None,
    loop=None,
    threshold_ms=WATCHDOG_THRESHOLD_MS,
    cooldown_sec=WATCHDOG_COOLDOWN_SEC,
    check_interval_sec=WATCHDOG_CHECK_INTERVAL_SEC,
    escalation_window_sec=WATCHDOG_ESCALATION_WINDOW_SEC,
):
    if last_alive is None:
        last_alive = LastAlive()
    if send_event is None:
        send_event = MagicMock()
    return WatchdogThread(
        last_alive=last_alive,
        send_event=send_event,
        loop=loop,
        threshold_ms=threshold_ms,
        cooldown_sec=cooldown_sec,
        check_interval_sec=check_interval_sec,
        escalation_window_sec=escalation_window_sec,
    )


# ---------------------------------------------------------------------------
# LastAlive container
# ---------------------------------------------------------------------------

class TestLastAlive:
    def test_default_value_is_zero(self):
        """
        Given a fresh LastAlive,
        When reading value,
        Then it is 0.0.
        """
        la = LastAlive()
        assert la.value == 0.0

    def test_can_be_written(self):
        """
        Given a LastAlive,
        When assigning a monotonic timestamp,
        Then value reflects the new timestamp.
        """
        la = LastAlive()
        la.value = 1234.5
        assert la.value == 1234.5


# ---------------------------------------------------------------------------
# Pinger coroutine
# ---------------------------------------------------------------------------

class TestPingerCoroutine:
    @pytest.mark.asyncio
    async def test_pinger_updates_last_alive_every_100ms(self):
        """
        Given a LastAlive container and a short interval,
        When pinger runs for two ticks,
        Then last_alive.value is updated at least once above 0.
        """
        # Arrange
        la = LastAlive()
        assert la.value == 0.0

        # Act — run pinger for just enough ticks using a cancellation after 2 sleeps
        tick_count = 0

        async def _run():
            nonlocal tick_count
            task = asyncio.create_task(pinger(last_alive=la, interval_sec=0.01))
            await asyncio.sleep(0.025)  # ~2 ticks at 10 ms
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await _run()

        # Assert
        assert la.value > 0.0

    @pytest.mark.asyncio
    async def test_pinger_uses_interval_sec(self):
        """
        Given a pinger with interval_sec=0.05,
        When we let it run for ~0.12 s,
        Then last_alive.value is updated above 0 (it ticked multiple times).
        """
        # Arrange
        la = LastAlive()
        assert la.value == 0.0

        # Act
        task = asyncio.create_task(pinger(last_alive=la, interval_sec=0.05))
        await asyncio.sleep(0.13)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # Assert: value is set (pinger ran at least once)
        assert la.value > 0.0

    @pytest.mark.asyncio
    async def test_pinger_stops_on_cancel(self):
        """
        Given a running pinger task,
        When the task is cancelled,
        Then it terminates cleanly (no uncaught exception).
        """
        la = LastAlive()
        task = asyncio.create_task(pinger(last_alive=la, interval_sec=0.01))
        await asyncio.sleep(0.015)
        task.cancel()
        # Should not raise anything other than CancelledError
        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# WatchdogThread — construction & daemon flag
# ---------------------------------------------------------------------------

class TestWatchdogThreadConstruction:
    def test_is_daemon_thread(self):
        """
        Given a WatchdogThread,
        When created,
        Then it is a daemon thread.
        """
        t = _make_thread()
        assert t.daemon is True

    def test_stop_event_is_threading_event(self):
        """
        Given a WatchdogThread,
        When inspecting internal _stop_event,
        Then it is a threading.Event instance.
        """
        t = _make_thread()
        assert isinstance(t._stop_event, threading.Event)

    def test_stop_sets_event(self):
        """
        Given a WatchdogThread,
        When stop() is called,
        Then _stop_event is set.
        """
        t = _make_thread()
        assert not t._stop_event.is_set()
        t.stop()
        assert t._stop_event.is_set()


# ---------------------------------------------------------------------------
# CI11: uses Event.wait, not time.sleep
# ---------------------------------------------------------------------------

class TestEventWaitNotSleep:
    def test_thread_uses_event_wait_not_time_sleep(self):
        """
        Given a WatchdogThread,
        When stop() is called before start(),
        Then run() exits on the first Event.wait() without sleeping.

        CI11: loop is `while not self._stop_event.wait(timeout=...)`.
        """
        t = _make_thread(check_interval_sec=10)  # huge interval — would hang if sleep
        t.stop()  # pre-set stop flag
        # run() should return immediately because stop_event is already set
        start = time.monotonic()
        t.run()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0  # < 1 s even though check_interval is 10 s

    def test_stop_event_interrupts_check_wait_promptly(self):
        """
        Given a running WatchdogThread with a large check interval,
        When stop() is called from another thread,
        Then the thread exits within 0.5 s.

        CI11: Event.wait(timeout) is interruptible; time.sleep is not.
        """
        t = _make_thread(check_interval_sec=30)  # would block for 30 s with sleep
        t.start()
        time.sleep(0.05)
        start = time.monotonic()
        t.stop()
        t.join(timeout=1.0)
        elapsed = time.monotonic() - start
        assert not t.is_alive()
        assert elapsed < 1.0


# ---------------------------------------------------------------------------
# CI9, CI10: detects block > threshold, fires hit
# ---------------------------------------------------------------------------

class TestWatchdogDetectsBlock:
    def test_thread_detects_block_over_threshold_and_fires_hit(self):
        """
        Given last_alive is stale (block > threshold_ms),
        When _check() is called,
        Then send_event is called once with a watchdog event dict.

        CI9, CI10.
        """
        # Arrange
        send_event = MagicMock()
        la = LastAlive()
        la.value = time.monotonic() - 2.0  # 2 s stale (>> 500 ms)

        t = _make_thread(
            last_alive=la,
            send_event=send_event,
            loop=None,
            threshold_ms=500,
        )

        # Act
        t._check()

        # Assert
        send_event.assert_called_once()
        event = send_event.call_args[0][0]
        assert event["kind"] == "watchdog"

    def test_no_hit_when_under_threshold(self):
        """
        Given last_alive is fresh (block < threshold_ms),
        When _check() is called,
        Then send_event is NOT called.
        """
        send_event = MagicMock()
        la = LastAlive()
        la.value = time.monotonic()  # just updated

        t = _make_thread(
            last_alive=la,
            send_event=send_event,
            threshold_ms=500,
        )

        t._check()

        send_event.assert_not_called()

    def test_no_hit_when_last_alive_zero(self):
        """
        Given last_alive is 0.0 (pinger hasn't started),
        When _check() is called,
        Then send_event is NOT called (CI15: sync app).
        """
        send_event = MagicMock()
        la = LastAlive()
        assert la.value == 0.0

        t = _make_thread(last_alive=la, send_event=send_event)
        t._check()

        send_event.assert_not_called()


# ---------------------------------------------------------------------------
# CI11: cooldown guard-check (not sleep)
# ---------------------------------------------------------------------------

class TestCooldownGuardCheck:
    def test_cooldown_10s_via_guard_check_not_sleep(self):
        """
        Given a recent hit (< cooldown_sec ago),
        When _check() is called again,
        Then send_event is NOT called a second time.

        CI11: cooldown is a guard-check (`if now - _last_hit_at < cooldown`).
        """
        # Arrange
        send_event = MagicMock()
        la = LastAlive()
        la.value = time.monotonic() - 2.0  # stale

        t = _make_thread(
            last_alive=la,
            send_event=send_event,
            threshold_ms=500,
            cooldown_sec=10,
        )

        # Act
        t._check()  # first hit — sends event
        la.value = time.monotonic() - 2.0  # still stale
        t._check()  # within cooldown — should be suppressed

        # Assert
        assert send_event.call_count == 1

    def test_cooldown_expires_fires_again(self):
        """
        Given a hit that occurred > cooldown_sec ago,
        When _check() is called,
        Then send_event is called again.
        """
        send_event = MagicMock()
        la = LastAlive()
        la.value = time.monotonic() - 2.0  # stale

        t = _make_thread(
            last_alive=la,
            send_event=send_event,
            threshold_ms=500,
            cooldown_sec=10,
        )

        t._check()  # first hit
        # Simulate cooldown already elapsed by resetting _last_hit_at
        t._last_hit_at = time.monotonic() - 11.0
        la.value = time.monotonic() - 2.0  # still stale
        t._check()  # should fire again

        assert send_event.call_count == 2


# ---------------------------------------------------------------------------
# CI14: severity escalation
# ---------------------------------------------------------------------------

class TestSeverityEscalation:
    def test_first_hit_warning_second_error_escalation(self):
        """
        Given two stale checks within escalation window,
        When both trigger a hit,
        Then first event severity is 'warning', second is 'error'.

        CI14.
        """
        events: list[dict] = []
        send_event = MagicMock(side_effect=lambda e: events.append(e))
        la = LastAlive()
        la.value = time.monotonic() - 2.0  # stale

        t = _make_thread(
            last_alive=la,
            send_event=send_event,
            threshold_ms=500,
            cooldown_sec=0,  # no cooldown for test
            escalation_window_sec=60,
        )

        t._check()  # first hit — warning
        la.value = time.monotonic() - 2.0  # reset stale
        t._check()  # second hit within 60 s — error

        assert len(events) == 2
        assert events[0]["severity"] == "warning"
        assert events[1]["severity"] == "error"

    def test_first_hit_after_window_reset_is_warning(self):
        """
        Given the escalation window has expired,
        When the next hit arrives,
        Then severity is 'warning' again.
        """
        events: list[dict] = []
        send_event = MagicMock(side_effect=lambda e: events.append(e))
        la = LastAlive()
        la.value = time.monotonic() - 2.0

        t = _make_thread(
            last_alive=la,
            send_event=send_event,
            threshold_ms=500,
            cooldown_sec=0,
            escalation_window_sec=60,
        )

        t._check()  # warning
        # Expire the window by resetting the policy's internal state
        t._policy._first_hit_in_window_at = time.monotonic() - 61.0
        t._last_hit_at = time.monotonic() - 1.0  # past cooldown (cooldown=0)
        la.value = time.monotonic() - 2.0
        t._check()  # should reset to warning

        assert events[1]["severity"] == "warning"


# ---------------------------------------------------------------------------
# CI15: sync app — no loop -> noop
# ---------------------------------------------------------------------------

class TestSyncAppNoop:
    def test_sync_app_no_loop_watchdog_idle_noop(self):
        """
        Given loop=None (sync application, no asyncio loop),
        When a block is detected and _check() would fire,
        Then send_event is called but the event has no stuck_tasks
        (loop is None so no snapshot is possible).

        CI15: watchdog thread works but loop is None -> no task snapshot.
        The event is still emitted (blocked loop detection still works via
        pinger simply not running — but here last_alive IS set, so we
        test that the thread still fires an event rather than crashing).

        Actually CI15 states: _target_loop is None -> nothing happens (no event).
        Re-reading: pinger doesn't run in sync apps so last_alive stays 0.0.
        This test verifies last_alive=0 means no event.
        """
        send_event = MagicMock()
        la = LastAlive()
        # last_alive stays 0.0 — pinger never ran (sync app)
        t = _make_thread(last_alive=la, send_event=send_event, loop=None)
        t._check()
        send_event.assert_not_called()


# ---------------------------------------------------------------------------
# Stuck tasks cap
# ---------------------------------------------------------------------------

class TestStuckTasksCap:
    def test_stuck_tasks_capped_at_10(self):
        """
        Given a loop with 20 running tasks,
        When a watchdog hit is collected,
        Then the event payload contains at most 10 stuck tasks (event-model §4.4).
        """
        # Arrange: simulate task snapshot returning 20 tasks
        send_event = MagicMock()
        la = LastAlive()
        la.value = time.monotonic() - 2.0  # stale

        t = _make_thread(
            last_alive=la,
            send_event=send_event,
            threshold_ms=500,
            cooldown_sec=0,
        )

        # Build 20 fake tasks
        fake_tasks = []
        for i in range(20):
            task = MagicMock(spec=asyncio.Task)
            coro = MagicMock()
            coro.__qualname__ = f"fake_coro_{i}"
            coro.__module__ = "fake_module"
            task.get_name.return_value = f"Task-{i}"
            task.get_coro.return_value = coro
            task.done.return_value = False
            fake_tasks.append(task)

        # Patch _collect_snapshot to return these fake tasks directly
        with patch.object(t, "_collect_snapshot", return_value=fake_tasks):
            t._check()

        event = send_event.call_args[0][0]
        assert len(event["payload"]["stuck_tasks"]) <= 10

    def test_watchdog_event_structure(self):
        """
        Given a stale last_alive and no loop,
        When a hit fires,
        Then the event dict has correct top-level structure.
        """
        events: list[dict] = []
        send_event = MagicMock(side_effect=lambda e: events.append(e))
        la = LastAlive()
        la.value = time.monotonic() - 2.0

        t = _make_thread(
            last_alive=la,
            send_event=send_event,
            threshold_ms=500,
            cooldown_sec=0,
        )
        t._check()

        assert len(events) == 1
        event = events[0]
        assert event["kind"] == "watchdog"
        assert "severity" in event
        assert "payload" in event
        payload = event["payload"]
        assert "block_duration_ms" in payload
        assert payload["block_duration_ms"] > 0
        assert "threshold_ms" in payload
        assert payload["threshold_ms"] == 500
        assert "stuck_tasks" in payload


# ---------------------------------------------------------------------------
# CI12: snapshot via call_soon_threadsafe + Future
# ---------------------------------------------------------------------------

class TestSnapshotCollection:
    def test_snapshot_collected_via_call_soon_threadsafe_future(self):
        """
        Given a loop that is running,
        When _collect_snapshot is called,
        Then it uses loop.call_soon_threadsafe to schedule snapshot collection
        (i.e., a Future is submitted to the loop's thread).

        CI12.
        """
        # Arrange
        la = LastAlive()
        la.value = time.monotonic() - 2.0

        mock_loop = MagicMock()
        # Simulate call_soon_threadsafe immediately invoking the callback
        def fake_call_soon_threadsafe(callback, *args):
            if args:
                callback(*args)
            else:
                callback()

        mock_loop.call_soon_threadsafe.side_effect = fake_call_soon_threadsafe

        t = _make_thread(last_alive=la, loop=mock_loop, threshold_ms=500)

        # Act
        t._collect_snapshot()

        # Assert: call_soon_threadsafe was called (CI12)
        mock_loop.call_soon_threadsafe.assert_called()

    def test_snapshot_timeout_returns_empty_list(self):
        """
        Given a loop that never delivers the snapshot (timeout),
        When _collect_snapshot is called,
        Then it returns an empty list (CI13: emit event with empty stuck_tasks).
        """
        # Arrange
        la = LastAlive()
        mock_loop = MagicMock()
        # call_soon_threadsafe does nothing (never resolves the future)
        mock_loop.call_soon_threadsafe.return_value = None

        t = _make_thread(
            last_alive=la,
            loop=mock_loop,
            threshold_ms=500,
        )

        # Act — use very short snapshot_timeout to avoid blocking test
        tasks = t._collect_snapshot(snapshot_timeout=0.01)

        # Assert
        assert isinstance(tasks, list)
        assert tasks == []

    def test_loop_none_snapshot_returns_empty_list(self):
        """
        Given loop=None,
        When _collect_snapshot is called,
        Then it returns an empty list immediately.
        """
        t = _make_thread(loop=None)
        result = t._collect_snapshot()
        assert result == []
