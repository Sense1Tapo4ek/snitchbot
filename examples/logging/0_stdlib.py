"""Logging demo: stdlib logging bridge.

`snitchbot.setup_logging()` attaches a handler to Python's standard
logging that forwards WARNING+ log records to Telegram as notifications.

Features demonstrated:
    1. Zero-config bridge — just call setup_logging()
    2. Extras from log records
    3. Error with traceback (exc_info=True)
    4. request_context propagation — trace_id attached automatically
    5. Dedup — repeated logs from same caller shown as x N

Prerequisites:
    cp .env.example .env
    uv run python examples/logging/0_stdlib.py
"""
import logging
import time

import snitchbot


def main():
    snitchbot.init("log-demo", live_dashboard=False)
    snitchbot.setup_logging()  # WARNING+ -> Telegram

    logger = logging.getLogger("myapp")

    # 1. Simple warning with extras
    logger.warning("Cache miss rate too high", extra={"miss_pct": 42})
    time.sleep(2)

    # 2. Error with traceback
    try:
        _ = 1 / 0
    except ZeroDivisionError:
        logger.error("Calculation failed", exc_info=True)
    time.sleep(2)

    # 3. Logging inside request_context — trace_id attached automatically
    with snitchbot.request_context(trace_id="req-abc-123", user_id=42):
        logger.warning("Slow database query in checkout")
    time.sleep(2)

    # 4. Dedup — repeated logs from same caller shown as x N
    for _ in range(5):
        logger.warning("Connection pool exhausted")
        time.sleep(0.5)

    time.sleep(3)
    print("Done. Check Telegram.")


if __name__ == "__main__":
    main()
