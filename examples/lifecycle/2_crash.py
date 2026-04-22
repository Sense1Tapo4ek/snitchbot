"""Lifecycle demo: Crash (Unhandled Exception).

Demonstrates how snitchbot handles an unexpected script failure in the main thread.

    1. snitchbot.init() emits a `startup` event.
    2. An unhandled exception occurs.
    3. snitchbot's `sys.excepthook` wrapper catches the exception.
    4. It emits a detailed `crash` event with the stack trace.
    5. Because the main thread crashed, it also emits a `shutdown` event
       with reason='crash'.

Expected Telegram output:
    ▶ lifecycle-crash started
    ━━━━━━━━━━━━━━━━━━
    pid        395236
    time       2026-04-14 14:47:49 UTC

    🔴 crash · lifecycle-crash · a26186
    ZeroDivisionError: division by zero
    Details
    time     2026-04-14 14:47:50 UTC
    pid      395236
    thread   MainThread
    origin   sys_excepthook
    Stack (top 3 user frames)

        <some_path>/examples/lifecycle/crash.py:35 in <module>()
        main()
        <some_path>/examples/lifecycle/crash.py:32 in main()
        _ = 1 / 0

    ⚠ lifecycle-crash crashed
    ━━━━━━━━━━━━━━━━━━
    pid        395236
    reason     crash
    time       2026-04-14 14:47:50 UTC
"""
import time

import snitchbot


def main():
    snitchbot.init("lifecycle-crash", live_dashboard=False)

    print("Script is running...")
    time.sleep(1.0)

    print("Simulating a fatal crash...")
    # This will trigger sys.excepthook and kill the process
    _ = 1 / 0

if __name__ == "__main__":
    main()
