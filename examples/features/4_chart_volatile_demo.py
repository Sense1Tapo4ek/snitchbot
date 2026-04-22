"""Chart demo: Volatile Metrics.

Demonstrates the /chart command with fast sampling and wildly jumping metrics.
Uses 1-second sampling interval for high-resolution charts.

    1. snitchbot.init() with sample_interval_sec=1
    2. Background threads simulate volatile CPU, memory, FDs, and threads
    3. After 60s of data, send /chart to the bot to see the charts

The script runs for 3 minutes to give you time to experiment with
different /chart commands:
    /chart              -> all 4 metrics, last 5m
    /chart cpu 1m       -> CPU only, last 1 minute
    /chart mem 2m       -> Memory only, last 2 minutes
    /chart fds 1m       -> File descriptors, last 1 minute
    /chart threads 1m   -> Thread count, last 1 minute
"""
import os
import random
import threading
import time

import snitchbot
from snitchbot import AnomalyConfig


def cpu_wave():
    """Alternate between high and low CPU in 10s cycles."""
    while True:
        # High CPU phase (5s)
        end = time.monotonic() + 5
        while time.monotonic() < end:
            _ = sum(i * i for i in range(10000))
        # Low CPU phase (5s)
        time.sleep(5)


def memory_wave():
    """Allocate and release memory in waves."""
    buffers = []
    while True:
        # Growth phase: allocate 10 MB chunks
        for _ in range(5):
            buf = bytearray(10 * 1024 * 1024)
            for i in range(0, len(buf), 4096):
                buf[i] = 1
            buffers.append(buf)
            time.sleep(2)
        # Release phase
        time.sleep(3)
        buffers.clear()
        time.sleep(5)


def fd_wave():
    """Open and close file descriptors in bursts."""
    while True:
        handles = []
        # Open phase
        for _ in range(20):
            handles.append(open(os.devnull, "rb"))
            time.sleep(0.5)
        # Close phase
        time.sleep(3)
        for h in handles:
            h.close()
        time.sleep(5)


def thread_wave():
    """Spawn and join threads in waves."""
    while True:
        threads = []
        for i in range(8):
            t = threading.Thread(
                target=lambda: time.sleep(random.uniform(5, 15)),
                daemon=True,
                name=f"wave-{i}",
            )
            t.start()
            threads.append(t)
            time.sleep(1)
        time.sleep(10)
        # Threads auto-die after sleep


def main():
    snitchbot.init(
        "chart-demo",
        sample_interval_sec=1,
        anomaly=AnomalyConfig(
            # Disable anomaly alerts — we just want charts
            rss=None,
            cpu=None,
            fds=None,
            threads=None,
        ),
    )

    print("Starting volatile metric generators...")
    for fn in (cpu_wave, memory_wave, fd_wave, thread_wave):
        threading.Thread(target=fn, daemon=True).start()

    print()
    print("Metrics are being sampled every 1 second.")
    print("Wait ~30s for data to accumulate, then try these commands in Telegram:")
    print()
    print("  /chart              -> all metrics, last 5 minutes")
    print("  /chart cpu 1m       -> CPU chart, last 1 minute")
    print("  /chart mem 2m       -> Memory chart, last 2 minutes")
    print("  /chart fds 1m       -> File descriptors, last 1 minute")
    print("  /chart threads 1m   -> Thread count, last 1 minute")
    print()
    print("Running for 3 minutes...")

    time.sleep(180)
    print("Done.")


if __name__ == "__main__":
    main()
