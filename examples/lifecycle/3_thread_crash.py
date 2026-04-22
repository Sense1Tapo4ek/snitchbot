"""Lifecycle demo: Background Thread Crash.

Demonstrates how snitchbot captures unhandled exceptions from non-main threads
via threading.excepthook. Unlike a main-thread crash, a background thread crash
does NOT terminate the process — the main thread continues running.

    1. snitchbot.init() emits a `startup` event and installs threading.excepthook.
    2. A background thread raises an unhandled RuntimeError.
    3. snitchbot's threading.excepthook sends a `crash` event (with thread name
       and stack trace) to Telegram.
    4. The main thread is unaffected and continues running.
    5. When the main thread exits normally, atexit fires -> `clean_exit` event.

Expected Telegram output:

    ▶ lifecycle-thread-crash started
    ━━━━━━━━━━━━━━━━━━
    pid        402500
    time       2026-04-14 15:05:00 UTC

    🔴 crash · lifecycle-thread-crash · b3f9a1
    RuntimeError: background thread exploded
    Details
    time     2026-04-14 15:05:01 UTC
    pid      402500
    thread   CrashWorker
    origin   threading_excepthook

    ■ lifecycle-thread-crash stopped
    ━━━━━━━━━━━━━━━━━━
    pid        402500
    reason     clean_exit
    time       2026-04-14 15:05:03 UTC

Prerequisites:
    cp .env.example .env
    uv run python examples/lifecycle/thread_crash.py
"""

import threading
import time

import snitchbot


def _crash_worker() -> None:
    """A background thread that raises an unhandled exception."""
    time.sleep(1.0)
    raise RuntimeError("background thread exploded")


def main() -> None:
    snitchbot.init("lifecycle-thread-crash", live_dashboard=False)

    t = threading.Thread(target=_crash_worker, name="CrashWorker", daemon=True)
    t.start()

    print("Main thread running. Background thread will crash in ~1 s.")
    # Wait long enough for the crash to be captured, then exit cleanly.
    time.sleep(3.0)
    print("Main thread finished. atexit will emit clean_exit.")


if __name__ == "__main__":
    main()
