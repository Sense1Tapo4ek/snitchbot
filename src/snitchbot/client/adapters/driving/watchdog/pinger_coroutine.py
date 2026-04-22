"""Asyncio pinger coroutine — updates last_alive timestamp every tick.

Runs as an asyncio Task inside the monitored event loop.
The WatchdogThread reads last_alive.value from a separate OS thread.

CI9: pinger is the liveness signal that the watchdog thread monitors.
"""
import asyncio
import time

from snitchbot.shared.constants import PINGER_INTERVAL_SEC


class LastAlive:
    """Thread-safe float holder for the pinger's last-alive timestamp.

    Written by the pinger coroutine (inside the event loop thread) and read
    by the WatchdogThread (OS thread). On CPython, float assignment is atomic
    at the GIL level, so no lock is needed for this single-writer / single-
    reader pattern.

    Default value 0.0 signals «pinger hasn't started yet» (CI15).
    """

    __slots__ = ("value",)

    def __init__(self) -> None:
        self.value: float = 0.0


async def pinger(
    *,
    last_alive: LastAlive,
    interval_sec: float = PINGER_INTERVAL_SEC,
) -> None:
    """Update last_alive.value every interval_sec. Runs forever until cancelled.

    Args:
        last_alive: Shared container written each tick and read by WatchdogThread.
        interval_sec: Tick interval in seconds (default PINGER_INTERVAL_SEC = 0.1).
    """
    while True:
        last_alive.value = time.monotonic()
        await asyncio.sleep(interval_sec)
