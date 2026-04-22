"""Helper: build crash event dict for asyncio task exceptions."""
import os
import time
from collections.abc import Callable

from snitchbot import __version__


def build_asyncio_crash_event(
    exc: BaseException,
    severity: str,
    extract_stack_fn: Callable,
) -> dict:
    """Build crash event dict with origin='asyncio_handler'.

    Args:
        exc: The exception from the asyncio context dict.
        severity: Pre-classified severity string.
        extract_stack_fn: callable(tb) -> list[dict] — extracts stack frames.

    Returns:
        Full envelope crash event dict ready to send via IPC.
    """
    return {
        "v": __version__,
        "ts": time.time(),
        "kind": "crash",
        "severity": severity,
        "pid": os.getpid(),
        "trace_id": None,
        "context": None,
        "payload": {
            "exception_type": type(exc).__name__,
            "message": str(exc)[:2000],
            "stack": extract_stack_fn(exc.__traceback__),
            "thread": None,
            "origin": "asyncio_handler",
        },
    }
