"""Logging demo: structlog processor.

`snitchbot.setup_structlog()` returns a structlog processor that forwards
WARNING+ events to Telegram. All structlog kwargs become extras in the alert.

Expected Telegram output:
    🟠 log.warning · structlog-demo · 5135f9
    Payment retry limit reached
    Details
        time     2026-04-17 13:38:14 UTC
        pid      1805173
        caller   examples/logging/1_structlog.py:79 in main()
    Extras
        provider   stripe
        retries   3
        order_id   ord-42

    🔴 log.error · structlog-demo · 6a0dca
    Webhook signature verification failed
    Details
        time     2026-04-17 13:38:16 UTC
        pid      1805173
        caller   examples/logging/1_structlog.py:89 in main()
    Extras
        provider   github
        event_type   push


    🔴 log.error · structlog-demo · d1560c
    Missing required key in API response
    Details
        time     2026-04-17 13:38:18 UTC
        pid      1805173
        caller   examples/logging/1_structlog.py:102 in main()
    Extras
        api   payments
    Exception: KeyError: 'orders'
    Traceback (most recent call last):
        File "examples/logging/1_structlog.py", line 100, in main
            _ = data["orders"]
    KeyError: 'orders'

"""
import time

import structlog

import snitchbot


def main():
    snitchbot.init("structlog-demo", live_dashboard=False)

    # Configure structlog with callsite info + snitchbot forwarder.
    # CallsiteParameterAdder adds file/line/func to each log event,
    # so snitchbot can show the correct caller in Telegram alerts.
    from structlog.processors import CallsiteParameter, CallsiteParameterAdder

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            CallsiteParameterAdder([
                CallsiteParameter.PATHNAME,
                CallsiteParameter.LINENO,
                CallsiteParameter.FUNC_NAME,
            ]),
            snitchbot.setup_structlog(),
            structlog.dev.ConsoleRenderer(),
        ],
    )

    log = structlog.get_logger()

    # Info — console only, not forwarded to Telegram
    log.info("Service started", version="1.2.3")

    time.sleep(2)

    # Warning — forwarded to Telegram with all kwargs as extras
    log.warning(
        "Payment retry limit reached",
        provider="stripe",
        retries=3,
        order_id="ord-42",
    )

    time.sleep(2)

    # Error — forwarded to Telegram
    log.error(
        "Webhook signature verification failed",
        provider="github",
        event_type="push",
    )

    time.sleep(2)

    # Error with traceback — exc_info is passed through to Telegram
    try:
        data = {"users": [1, 2, 3]}
        _ = data["orders"]
    except KeyError:
        log.error(
            "Missing required key in API response",
            api="payments",
            exc_info=True,
        )

    time.sleep(3)
    print("Done. Check Telegram for 3 structlog alerts.")


if __name__ == "__main__":
    main()
