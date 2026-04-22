"""Anomaly demo: File Descriptors.

Demonstrates 3 detection modes for FDs:
- **Ceiling**: Hard FD limit (ulimit protection) -> severity `error`
- **Spike**: FD count growing vs baseline -> severity `error`
- **Drop**: Pool collapse (disabled in this demo)

    1. We configure a low ceiling (max_fds=50) for the demo.
    2. We open files without closing them, leaking file descriptors.
    3. The sidecar detects the FD count exceeding the ceiling.

Expected Telegram output:
    🔴 anomaly · anomaly-fds · f88221 × 4
    FD ceiling: 55 (limit 50)
    Details
        first    2026-04-17 10:59:17 UTC
        last     2026-04-17 10:59:27 UTC
        pid      1472155
        type      fds_ceiling
        window    1m
        baseline  33
        current   55
"""
import os
import time

import snitchbot
from snitchbot import AnomalyConfig, FdAnomalyConfig


def main():
    snitchbot.init(
        "anomaly-fds",
        live_dashboard=False,
        anomaly=AnomalyConfig(
            fds=FdAnomalyConfig(
                duration="1m",
                baseline_duration="5m",
                max_fds=50,                 # Ceiling: alert if FDs > 50
                spike_ratio=1.5,            # Spike: alert if FDs grow 1.5x
                min_spike_delta=20,         # ... and by at least 20
                drop_ratio=None,            # Drop: disabled for this demo
            ),
            # Disable other detectors for a clean demo
            rss=None,
            cpu=None,
            threads=None,
        ),
    )

    print("Phase 1: Warmup (10s)...")
    time.sleep(10)

    print("Phase 2: Leaking file descriptors slowly for 100 seconds...")
    held_fds = []

    for _ in range(50):
        held_fds.append(open(os.devnull, "rb"))
        print(f"  [+] Leaked FD (total leaked: {len(held_fds)})")
        time.sleep(2.0)

    print("Done. The FD leak alert (severity: error) should be in Telegram.")


if __name__ == "__main__":
    main()
