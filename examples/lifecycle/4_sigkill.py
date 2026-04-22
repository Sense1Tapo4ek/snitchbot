"""Lifecycle demo: Hard Kill (SIGKILL / OOM Kill).

Demonstrates how snitchbot detects an ungracefully terminated process.

This covers two real-world scenarios:
- **kill -9** (manual hard kill, Docker force-stop)
- **OOM killer** (Linux kernel kills the process when memory exceeds cgroup limit)

Both look identical from snitchbot's perspective: the process vanishes
instantly — no atexit, no signal handlers, no cleanup. The sidecar
detects the disappearance and reports it.

How the goodbye protocol works:
    1. snitchbot.init() emits a `startup` event.
    2. The process is killed (SIGKILL or OOM) — no IPC sent.
    3. Sidecar polls PIDs every 5s via os.kill(pid, 0).
    4. Dead PID detected -> 10s grace period (drains any in-flight IPC).
    5. Grace expires, no shutdown received -> sidecar emits `killed` event.

Expected Telegram output:

    ▶ lifecycle-sigkill started
    ━━━━━━━━━━━━━━━━━━
    pid        393433
    time       2026-04-14 14:46:58 UTC

    ⚠ lifecycle-sigkill killed
    ━━━━━━━━━━━━━━━━━━
    pid        393433
    reason     killed
    time       2026-04-14 14:47:10 UTC

In production, OOM kill looks the same:
    Your container hits the memory limit -> kernel sends SIGKILL ->
    snitchbot detects it and sends the `killed` notification.

Prerequisites:
    cp .env.example .env
    uv run python examples/lifecycle/sigkill.py
"""
import os
import signal
import time

import snitchbot


def main():
    snitchbot.init("lifecycle-sigkill", live_dashboard=False)

    print("Script is running...")
    time.sleep(3.0)

    print(f"Sending SIGKILL (kill -9) to PID {os.getpid()}...")
    print("No cleanup runs. Sidecar will detect death in ~15s.")
    # The kernel destroys the process immediately.
    # This is exactly what happens during OOM kill.
    os.kill(os.getpid(), signal.SIGKILL)


if __name__ == "__main__":
    main()
