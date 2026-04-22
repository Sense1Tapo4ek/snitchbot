"""threading.excepthook driving adapter.

Translates worker-thread unhandled exceptions into crash events.

CI1: chains to the previous hook
CI2: never raises out of the hook
CI3/CI36: thread crash does NOT emit lifecycle/shutdown — process stays alive
"""
import logging
import os
import threading
import time

from snitchbot import __version__

logger = logging.getLogger("snitchbot.client.adapters.driving.excepthooks.threading_excepthook")

_original_excepthook = None


def install(*, send_event, classify_severity, extract_stack):
    """Install our threading.excepthook, chaining to the previous one.

    Args:
        send_event: callable(event_dict) — sends an event via IPC.
        classify_severity: callable(exc_type) -> str — returns severity string.
        extract_stack: callable(exc_tb) -> list[dict] — extracts stack frames.
    """
    global _original_excepthook
    _original_excepthook = threading.excepthook

    def hook(args):
        try:
            # Python ignores SystemExit in threads — we do too (per spec §3.2)
            if issubclass(args.exc_type, SystemExit):
                return

            severity = classify_severity(args.exc_type)
            frames = extract_stack(args.exc_traceback)
            thread_name = args.thread.name if args.thread is not None else "unknown"

            crash_event = {
                "v": __version__,
                "ts": time.time(),
                "kind": "crash",
                "severity": severity,
                "pid": os.getpid(),
                "trace_id": None,
                "context": None,
                "payload": {
                    "exception_type": args.exc_type.__name__,
                    "message": str(args.exc_value)[:2000],
                    "stack": frames,
                    "thread": thread_name,
                    "origin": "threading_excepthook",
                },
            }
            send_event(crash_event)
            # CI3/CI36: do NOT emit lifecycle/shutdown — thread crash != process death
        except Exception:
            # CI2: never raise out of hook
            logger.debug("threading.excepthook internal error", exc_info=True)
        finally:
            if _original_excepthook is not None:
                _original_excepthook(args)

    threading.excepthook = hook


def uninstall():
    """Restore the original threading.excepthook."""
    global _original_excepthook
    if _original_excepthook is not None:
        threading.excepthook = _original_excepthook
        _original_excepthook = None
