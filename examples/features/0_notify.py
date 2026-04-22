"""Feature demo: Manual Notifications.

The simplest way to send an alert to Telegram — `snitchbot.notify()`.
Use it for business events, warnings, or anything worth knowing about.

    snitchbot.notify("text", severity="warning", extras={...})

Severity levels:
    - "warning" (default) -> 🟠
    - "error"             -> 🔴
    - "critical"          -> 🟣

Expected Telegram output:
    🟠 notify · notify-demo · f966e3
    Starting checkout process
    Details
        time     2026-04-17 12:42:47 UTC
        pid      1718711
        caller   examples/features/notify.py:33 in main()
        Extras
        cart_size   3
        user   Alice

    🔴 notify · notify-demo · 2eec9c
    Division failed in payment calculator
    Details
        time     2026-04-17 12:52:35 UTC
        pid      1732227
        caller   examples/features/notify.py:51 in main()
    Exception: ZeroDivisionError: division by zero
    Traceback (most recent call last):
        File "examples/features/notify.py", line 51, in main
            _ = 1 / 0
        ZeroDivisionError: division by zero
"""
import time

import snitchbot


def main():
    snitchbot.init("notify-demo", live_dashboard=False)

    # Simple warning
    snitchbot.notify(
        "Starting checkout process",
        severity="warning",
        extras={"cart_size": 3, "user": "Alice"},
    )
    print("Sent warning notification.")

    time.sleep(2)

    # Error with exc_info — attach the current exception
    try:
        _ = 1 / 0
    except ZeroDivisionError:
        snitchbot.notify(
            "Division failed in payment calculator",
            severity="error",
            exc_info=True,  # attaches the traceback
        )
    print("Sent error notification with traceback.")

    time.sleep(3)
    print("Done. Check Telegram.")


if __name__ == "__main__":
    main()
