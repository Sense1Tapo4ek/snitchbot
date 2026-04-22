"""Anomaly demo: Asyncio Watchdog — Escalating Stalls.

Demonstrates all 3 severity levels with progressively longer event loop blocks:

    Phase 1: 0.7s block -> warning (> 500ms threshold)
    Phase 2: 2.5s block -> error (> 2000ms error_threshold)
    Phase 3: 6.0s block -> critical (> 5000ms critical_threshold)

Each block is separated by a cooldown period so the watchdog fires
independently for each.

Expected Telegram output (3 messages):
    🟠 watchdog · anomaly-watchdog · 7c6497
    Event loop blocked for 588 ms (threshold 500 ms)
    Details
        time     2026-04-17 11:25:10 UTC
        pid      1580124
        loop   <_UnixSelectorEventLoop running=True closed=False debug=False>

    🔴 watchdog · anomaly-watchdog · 7c6497 × 2
    Event loop blocked for 690 ms (threshold 500 ms)
    Details
        first    2026-04-17 11:25:10 UTC
        last     2026-04-17 11:25:20 UTC
        pid      1580124
        loop   <_UnixSelectorEventLoop running=True closed=False debug=False>

    🟣 watchdog · anomaly-watchdog · 732334
    Event loop blocked for 5699 ms (threshold 500 ms)
    Details
        time     2026-04-17 11:25:24 UTC
        pid      1580124
        loop   <_UnixSelectorEventLoop running=True closed=False debug=False>
        Stuck tasks (3)

    Innocent-Worker · background_task

    examples/anomaly_detection/watchdog.py:55 in background_task
        Task-1 · main

    examples/anomaly_detection/watchdog.py:97 in main
"""
import asyncio
import time

import snitchbot
from snitchbot import AnomalyConfig, WatchdogConfig


async def background_task():
    """A harmless task that gets stuck when the main task blocks the loop."""
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass


async def main():
    snitchbot.init(
        "anomaly-watchdog",
        live_dashboard=False,
        anomaly=AnomalyConfig(
            watchdog=WatchdogConfig(
                threshold_ms=500,               # Warning: 500ms stall
                error_threshold_ms=2000,         # Error: 2s hard lock
                critical_threshold_ms=5000,      # Critical: 5s dead lock
                escalation_window="1m",
                cooldown_sec=5,                  # Short cooldown for demo
            ),
            rss=None,
            cpu=None,
            fds=None,
            threads=None,
        ),
    )

    t = asyncio.create_task(background_task(), name="Innocent-Worker")

    print("Phase 1: Minor stall (0.7s) -> warning...")
    time.sleep(0.7)
    await asyncio.sleep(1)  # let watchdog fire + recover

    print("         Cooldown (6s)...")
    await asyncio.sleep(6)

    print("Phase 2: Hard lock (2.5s) -> error...")
    time.sleep(2.5)
    await asyncio.sleep(1)

    print("         Cooldown (6s)...")
    await asyncio.sleep(6)

    print("Phase 3: Dead lock (6.0s) -> critical...")
    time.sleep(6.0)
    await asyncio.sleep(1)

    print("Phase 4: Flushing events (5s)...")
    await asyncio.sleep(5)

    t.cancel()
    print("Done. Check Telegram for 3 watchdog alerts.")


if __name__ == "__main__":
    asyncio.run(main())
