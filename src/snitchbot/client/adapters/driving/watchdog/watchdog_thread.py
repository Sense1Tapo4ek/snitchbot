"""Watchdog daemon thread — checks event loop liveness every CHECK_INTERVAL_SEC.

Fires a watchdog event when the loop is blocked longer than THRESHOLD_MS.

CI9/CI10: detects block > threshold, fires hit with severity + payload.
CI11: uses threading.Event.wait(timeout) — NOT time.sleep. This makes both
      the check interval and the cooldown guard-check interruptible by stop().
CI12: snapshot of asyncio.all_tasks() collected via call_soon_threadsafe + future.
CI13: snapshot timeout -> event emitted with empty stuck_tasks list.
CI14: severity escalation — first hit 'warning', next hits within 60 s -> 'error'.
CI15: if last_alive.value == 0.0 (pinger never ran, sync app) -> noop.
"""
import asyncio
import concurrent.futures
import logging
import os
import threading
import time
from collections.abc import Callable

from snitchbot import __version__
from snitchbot.client.adapters.driving.watchdog.pinger_coroutine import LastAlive
from snitchbot.client.domain.services.watchdog_policy_service import WatchdogPolicyService
from snitchbot.shared.constants import (
    WATCHDOG_CHECK_INTERVAL_SEC,
    WATCHDOG_COOLDOWN_SEC,
    WATCHDOG_ESCALATION_WINDOW_SEC,
    WATCHDOG_THRESHOLD_MS,
)
from snitchbot.shared.domain import WatchdogConfig

logger = logging.getLogger("snitchbot.client.adapters.driving.watchdog.watchdog_thread")

_DEFAULT_SNAPSHOT_TIMEOUT: float = 1.0
_MAX_STUCK_TASKS: int = 10
_MAX_STACK_FRAMES: int = 20


class WatchdogThread(threading.Thread):
    """Daemon thread that monitors asyncio event loop liveness.

    Args:
        last_alive: Shared LastAlive container written by the pinger coroutine.
        send_event: Callable(event_dict) — dispatches a watchdog event via IPC.
        loop: The asyncio event loop being monitored, or None for sync apps.
        threshold_ms: Block duration that triggers a hit (default 500 ms).
        cooldown_sec: Minimum gap between consecutive hits (default 10 s).
            Implemented as a guard-check, not sleep (CI11).
        check_interval_sec: How often the thread checks the timestamp (default 0.2 s).
        escalation_window_sec: Window for severity escalation (default 60 s).
    """

    def __init__(
        self,
        *,
        last_alive: LastAlive,
        send_event: Callable[[dict], None],
        loop: asyncio.AbstractEventLoop | None,
        threshold_ms: float = WATCHDOG_THRESHOLD_MS,
        cooldown_sec: float = WATCHDOG_COOLDOWN_SEC,
        check_interval_sec: float = WATCHDOG_CHECK_INTERVAL_SEC,
        escalation_window_sec: float = WATCHDOG_ESCALATION_WINDOW_SEC,
        watchdog_config: WatchdogConfig | None = None,
    ) -> None:
        super().__init__(daemon=True, name="snitchbot-watchdog")
        self._last_alive = last_alive
        self._send_event = send_event
        self._loop = loop

        # v2: WatchdogConfig overrides individual params when provided
        if watchdog_config is not None:
            self._threshold_ms = float(watchdog_config.threshold_ms)
            self._cooldown_sec = float(watchdog_config.cooldown_sec)
            self._enabled = watchdog_config.enabled
            esc_window = float(watchdog_config.escalation_window_sec)
            error_ms = watchdog_config.error_threshold_ms
            critical_ms = watchdog_config.critical_threshold_ms
        else:
            self._threshold_ms = threshold_ms
            self._cooldown_sec = cooldown_sec
            self._enabled = True
            esc_window = float(escalation_window_sec)
            error_ms = None
            critical_ms = None

        self._check_interval_sec = check_interval_sec
        self._stop_event = threading.Event()
        self._last_hit_at: float = 0.0
        self._first_hit_in_window_at: float = 0.0
        self._policy = WatchdogPolicyService(
            escalation_window_sec=esc_window,
            error_threshold_ms=error_ms,
            critical_threshold_ms=critical_ms,
        )

    # ------------------------------------------------------------------
    # Thread lifecycle
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Main loop: wait -> check -> repeat. CI11: Event.wait not sleep."""
        if not self._enabled:
            return
        while not self._stop_event.wait(timeout=self._check_interval_sec):
            self._check()

    def stop(self) -> None:
        """Signal the thread to exit. Returns immediately; call join() to wait."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Core check
    # ------------------------------------------------------------------

    def _check(self) -> None:
        """Single liveness check. Called every tick from run()."""
        now = time.monotonic()
        last = self._last_alive.value

        # CI15: pinger hasn't started (sync app) -> noop
        if last == 0.0:
            return

        block_ms = (now - last) * 1000.0
        if block_ms < self._threshold_ms:
            return

        # CI11: cooldown guard-check — not a sleep
        if self._cooldown_sec > 0 and now - self._last_hit_at < self._cooldown_sec:
            return

        # Wait for recovery to measure actual block duration.
        # Poll until pinger updates last_alive or max 10s timeout.
        block_start = last
        max_wait = 10.0
        wait_deadline = now + max_wait
        while not self._stop_event.is_set():
            time.sleep(self._check_interval_sec)
            current_last = self._last_alive.value
            if current_last > block_start:
                # Loop recovered — measure actual duration
                break
            if time.monotonic() > wait_deadline:
                # Still blocked after max_wait — report what we have
                break

        actual_now = time.monotonic()
        actual_block_ms = (actual_now - block_start) * 1000.0

        self._last_hit_at = actual_now
        severity = self._policy.compute_severity(actual_now, block_ms=actual_block_ms)
        self._first_hit_in_window_at = self._policy._first_hit_in_window_at

        # CI12: collect stuck-task snapshot via call_soon_threadsafe + future
        tasks = self._collect_snapshot()

        event = self._build_event(
            block_ms=actual_block_ms,
            severity=severity,
            tasks=tasks,
        )
        try:
            self._send_event(event)
        except Exception:
            logger.debug("watchdog send error", exc_info=True)  # I9: never raise from watchdog

    # ------------------------------------------------------------------
    # Snapshot collection  (CI12, CI13)
    # ------------------------------------------------------------------

    def _collect_snapshot(
        self,
        snapshot_timeout: float = _DEFAULT_SNAPSHOT_TIMEOUT,
    ) -> list:
        """Collect asyncio.all_tasks() from the loop thread.

        CI12: submitted via call_soon_threadsafe + Future.
        CI13: if timeout expires -> return empty list; caller emits event
              with empty stuck_tasks (loop still blocked).
        """
        if self._loop is None:
            return []

        future: concurrent.futures.Future = concurrent.futures.Future()

        def _snapshot() -> None:
            try:
                tasks = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
                future.set_result(tasks)
            except Exception as exc:
                future.set_exception(exc)

        try:
            self._loop.call_soon_threadsafe(_snapshot)
        except RuntimeError:
            # Loop is closed or not running
            return []

        try:
            return future.result(timeout=snapshot_timeout)
        except (concurrent.futures.TimeoutError, Exception):
            # CI13: timeout or any failure -> empty list
            logger.debug("watchdog snapshot timeout", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Event builder
    # ------------------------------------------------------------------

    def _build_event(
        self,
        *,
        block_ms: float,
        severity: str,
        tasks: list,
    ) -> dict:
        """Build the watchdog event dict.

        Capped at _MAX_STUCK_TASKS tasks. Each task's stack is capped at
        _MAX_STACK_FRAMES frames (event-model §4.4, §7).
        """
        stuck_tasks = []
        for task in tasks[:_MAX_STUCK_TASKS + 5]:  # over-fetch to compensate filtered
            # Skip snitchbot internal tasks — users don't need to see our pinger
            task_name = task.get_name()
            if task_name.startswith("snitchbot-"):
                continue
            if len(stuck_tasks) >= _MAX_STUCK_TASKS:
                break
            coro = task.get_coro()
            qualname = getattr(coro, "__qualname__", repr(coro))
            module = getattr(coro, "__module__", "")
            coro_path = f"{module}.{qualname}" if module else qualname

            try:
                stack_frames = task.get_stack()
                stack_strings = [
                    f"{f.f_code.co_filename}:{f.f_lineno} in {f.f_code.co_name}"
                    for f in stack_frames[:_MAX_STACK_FRAMES]
                ]
            except Exception:
                logger.debug("watchdog task stack extraction failed", exc_info=True)
                stack_strings = []

            stuck_tasks.append(
                {
                    "name": task.get_name(),
                    "coro": coro_path,
                    "stack": stack_strings,
                }
            )

        loop_id = repr(self._loop) if self._loop is not None else "none"

        return {
            "v": __version__,
            "ts": time.time(),
            "kind": "watchdog",
            "severity": severity,
            "pid": os.getpid(),
            "trace_id": None,
            "context": None,
            "payload": {
                "block_duration_ms": round(block_ms, 2),
                "threshold_ms": self._threshold_ms,
                "loop_id": loop_id,
                "stuck_tasks": stuck_tasks,
            },
        }
