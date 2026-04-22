"""Anomaly demo: CPU.

Demonstrates 3 detection modes for CPU:
- **Ceiling**: Hard CPU% limit -> severity `error`
- **Spike**: CPU grows vs baseline -> severity `warning`
- **Drop**: CPU starvation (disabled in this demo)

    1. We configure the CPU detector with a low ceiling (50%) for the demo.
    2. A background daemon thread runs a tight mathematical loop, saturating a core.
    3. The sidecar observes the sustained load and fires a ceiling alert.

Expected Telegram output:
    🔴 anomaly · anomaly-cpu · 063f00 × 4
    CPU ceiling: 91% (limit 50%)
    Details
        first    2026-04-17 10:56:30 UTC
        last     2026-04-17 10:56:45 UTC
        pid      1462735
        type      cpu_ceiling
        window    30s
        baseline  42%
        current   91%
"""
import threading
import time

import snitchbot
from snitchbot import AnomalyConfig, CpuAnomalyConfig


def cpu_burner():
    """Tight loop to saturate one CPU core."""
    while True:
        _ = 2 ** 1000


def main():
    snitchbot.init(
        "anomaly-cpu",
        live_dashboard=False,
        anomaly=AnomalyConfig(
            cpu=CpuAnomalyConfig(
                duration="30s",
                baseline_duration="2m",
                max_percent=50.0,           # Ceiling: alert if CPU > 50%
                spike_ratio=2.5,            # Spike: alert if CPU grows 2.5x
                min_spike_delta=30.0,       # ... and by at least 30%
                drop_ratio=None,            # Drop: disabled for this demo
            ),
            # Disable other detectors for a clean demo
            rss=None,
            fds=None,
            threads=None,
        ),
    )

    print("Phase 1: Warmup (20s)...")
    time.sleep(20)

    print("Phase 2: Starting CPU burner thread. It will run for 40s...")
    t = threading.Thread(target=cpu_burner, daemon=True, name="burner")
    t.start()

    # Wait long enough for window averaging to detect the spike
    time.sleep(40)

    print("Done. The CPU alert should be in Telegram now.")


if __name__ == "__main__":
    main()
