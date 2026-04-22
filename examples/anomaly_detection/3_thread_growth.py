"""Anomaly demo: Threads.

Demonstrates 3 detection modes for threads:
- **Ceiling**: Hard thread limit -> severity `error`
- **Spike**: Thread count growing vs baseline -> severity `warning`
- **Drop**: Worker collapse (disabled in this demo)

    1. We build a baseline of threads (usually just MainThread + snitchbot watchdog).
    2. We suddenly spawn 10 new daemon threads that do nothing (sleep).
    3. The sidecar detects the jump against the baseline.

Expected Telegram output:
    🟠 anomaly · anomaly-threads · 7ee02b × 2
    Thread growth: 5 -> 12 (+6)
    Details
        first    2026-04-17 11:21:32 UTC
        last     2026-04-17 11:21:37 UTC
        pid      1566796
        type      threads_spike
        window    15s
        baseline  5
        current   12

"""
import threading
import time

import snitchbot
from snitchbot import AnomalyConfig, ThreadAnomalyConfig


def idle_worker():
    time.sleep(3600)


def main():
    snitchbot.init(
        "anomaly-threads",
        live_dashboard=False,
        anomaly=AnomalyConfig(
            threads=ThreadAnomalyConfig(
                duration="15s",             # Short window: 3 samples
                baseline_duration="1m",     # Baseline from warmup
                max_threads=None,           # Ceiling: disabled
                spike_ratio=1.5,            # Spike: alert if threads grow 1.5x
                min_spike_delta=5,          # ... and by at least 5
                drop_ratio=None,            # Drop: disabled for this demo
            ),
            # Disable other detectors for a clean demo
            rss=None,
            cpu=None,
            fds=None,
        ),
    )

    print("Phase 1: Warmup (60s) - building thread baseline...")
    time.sleep(60)

    print("Phase 2: Spawning 10 new idle threads...")
    for i in range(10):
        threading.Thread(target=idle_worker, daemon=True, name=f"idler-{i}").start()

    print("Phase 3: Waiting for sidecar to detect spike (20s)...")
    time.sleep(20)

    print("Done. Check Telegram.")


if __name__ == "__main__":
    main()
