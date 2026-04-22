"""sys.excepthook driving adapter.

Translates main-thread unhandled exceptions into crash + lifecycle/shutdown events.

CI1: chains to the previous hook (never breaks existing handlers)
CI2: never raises out of the hook
CI3: only sys.excepthook emits lifecycle shutdown reason="crash"
"""
import logging
import os
import sys
import time

from snitchbot import __version__

logger = logging.getLogger("snitchbot.client.adapters.driving.excepthooks.sys_excepthook")

_original_excepthook = None


def install(*, send_event, classify_severity, extract_stack, build_shutdown):
    """Install our sys.excepthook, chaining to the previous one.

    Args:
        send_event: callable(event_dict) — sends an event via IPC.
        classify_severity: callable(exc_type) -> str — returns severity string.
        extract_stack: callable(exc_tb) -> list[dict] — extracts stack frames.
        build_shutdown: callable(reason=str) -> dict|None — builds shutdown event,
            returns None if already sent (dedup, CI18).
    """
    global _original_excepthook
    _original_excepthook = sys.excepthook

    def hook(exc_type, exc_value, exc_tb):
        try:
            severity = classify_severity(exc_type)
            frames = extract_stack(exc_tb)
            crash_event = {
                "v": __version__,
                "ts": time.time(),
                "kind": "crash",
                "severity": severity,
                "pid": os.getpid(),
                "trace_id": None,
                "context": None,
                "payload": {
                    "exception_type": exc_type.__name__,
                    "message": str(exc_value)[:2000],
                    "stack": frames,
                    "thread": "MainThread",
                    "origin": "sys_excepthook",
                },
            }
            send_event(crash_event)

            shutdown = build_shutdown(reason="crash")
            if shutdown is not None:
                send_event(shutdown)
        except Exception:
            # CI2: never let our hook crash the app
            logger.debug("sys.excepthook internal error", exc_info=True)
        finally:
            if _original_excepthook is not None:
                _original_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


def uninstall():
    """Restore the original sys.excepthook."""
    global _original_excepthook
    if _original_excepthook is not None:
        sys.excepthook = _original_excepthook
        _original_excepthook = None
