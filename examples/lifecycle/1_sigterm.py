"""Lifecycle demo: Graceful Shutdown (SIGTERM / SIGINT).

Demonstrates how snitchbot reacts to termination signals (like Docker stop,
Kubernetes drain, or pressing Ctrl+C).

    1. snitchbot.init() emits a `startup` event and registers signal handlers.
    2. The script receives a SIGTERM signal.
    3. snitchbot's signal handler intercepts it, emits a `shutdown` event
       with reason='sigterm', and then chains to the default OS behavior
       to terminate the process.

Expected Telegram output:
    ▶ lifecycle-sigterm started
    ━━━━━━━━━━━━━━━━━━
    pid        398338
    time       2026-04-14 14:49:24 UTC

    ■ lifecycle-sigterm stopped
    ━━━━━━━━━━━━━━━━━━
    pid        398338
    reason     sigterm
    time       2026-04-14 14:49:25 UTC

"""
import os
import signal
import time

import snitchbot


def main():
    snitchbot.init("lifecycle-sigterm", live_dashboard=False)

    print("Script is running...")
    time.sleep(1.0)

    print(f"Sending SIGTERM to my own PID ({os.getpid()})...")
    # In the real world, this signal comes from the OS, Docker, or systemd.
    os.kill(os.getpid(), signal.SIGTERM)

    # This code will never be reached because the default SIGTERM behavior
    # (which snitchbot calls after sending the event) terminates the process.
    time.sleep(5.0)
    print("You will never see this.")

if __name__ == "__main__":
    main()
