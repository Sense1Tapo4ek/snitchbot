"""Lifecycle demo: Clean Exit.

Demonstrates the normal lifecycle of a Python script using snitchbot.

    1. snitchbot.init() emits a `startup` event.
    2. The script performs its work and reaches the end normally.
    3. The registered `atexit` hook automatically emits a `shutdown` event
       with reason='clean_exit' just before the Python interpreter exits.

Expected Telegram output:

     ▶ lifecycle-clean started
    ━━━━━━━━━━━━━━━━━━
    pid        393433
    time       2026-04-14 14:46:58 UTC

    ■ lifecycle-clean stopped
    ━━━━━━━━━━━━━━━━━━
    pid        393433
    reason     clean_exit
    time       2026-04-14 14:47:00 UTC
"""
import time

import snitchbot


def main():
    snitchbot.init("lifecycle-clean", live_dashboard=False)

    print("Script is running...")
    time.sleep(2.0)  # Simulating some work

    print("Script finished successfully. atexit hook will run now.")
    # No explicit shutdown call is needed; snitchbot handles it automatically.

if __name__ == "__main__":
    main()
