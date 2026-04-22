"""Anomaly demo: Memory (RSS).

Demonstrates 3 detection modes for memory:
- **Ceiling**: Hard RSS limit -> severity `error`
- **Spike**: RSS grows vs baseline -> severity `warning`
- **Drop**: RSS drops (disabled here — normal for GC)

    1. snitchbot.init() starts the sidecar.
    2. We wait 60 seconds to build a "normal" baseline of memory usage.
    3. We allocate a ~150 MB buffer and write to it (forcing physical allocation).
    4. Within a few seconds, the sidecar samples the new RSS, compares it to
       the baseline, and triggers the anomaly.

Expected Telegram output:
    🟠 anomaly · anomaly-rss · a7af9c × 2
    RSS spike: 183 MB (baseline 70 MB, +160%)
    Details
        first    2026-04-17 11:17:40 UTC
        last     2026-04-17 11:17:45 UTC
        pid      1550371
        type      rss_spike
        window    15s
        baseline  70 MB
        current   183 MB
"""
import time

import snitchbot
from snitchbot import AnomalyConfig, RssAnomalyConfig


def main():
    snitchbot.init(
        "anomaly-rss",
        live_dashboard=False,
        anomaly=AnomalyConfig(
            rss=RssAnomalyConfig(
                duration="15s",             # Short window: 3 samples (15s / 5s)
                baseline_duration="1m",     # Baseline: 12 samples (60s / 5s)
                max_mb=None,                # Ceiling: disabled
                spike_ratio=1.5,            # Spike: alert if RSS grows 1.5x
                min_spike_mb=50.0,          # ... and by at least 50 MB
                drop_ratio=None,            # Drop: disabled (normal for GC)
            ),
            # Disable other detectors for a clean demo
            cpu=None,
            fds=None,
            threads=None,
        ),
    )

    print("Phase 1: Warmup (60s) - building memory baseline...")
    time.sleep(60)

    print("Phase 2: Allocating 150 MB of memory...")
    # Create a large bytearray and touch it so the OS actually allocates physical pages (RSS)
    big_buffer = bytearray(150 * 1024 * 1024)
    for i in range(0, len(big_buffer), 4096):
        big_buffer[i] = 1

    print("Phase 3: Waiting for sidecar to detect spike (20s)...")
    time.sleep(20)

    print("Done. Check Telegram for the RSS spike alert.")


if __name__ == "__main__":
    main()
