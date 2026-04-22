"""stdlib logging handler that forwards WARNING+ records to snitchbot sidecar.

"""
import logging
import sys
import threading
import traceback
from collections.abc import Callable
from typing import Any

__all__ = ["SnitchbotLoggingHandler"]


# Standard LogRecord attributes that are NOT user-supplied extras (§5.1).
_STANDARD_LOG_ATTRS: frozenset[str] = frozenset(
    [
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "getMessage",
        "taskName",
    ]
)

# Thread-local recursion guard (L5).
_in_handler = threading.local()


def _extract_extras(record: logging.LogRecord) -> dict[str, Any]:
    """Return user-supplied extra attrs from a LogRecord (§5.1)."""
    return {
        k: v
        for k, v in record.__dict__.items()
        if k not in _STANDARD_LOG_ATTRS and not k.startswith("_")
    }

def _build_exception(exc_info: Any) -> dict[str, Any] | None:
    """Build a minimal exception dict from exc_info triple, or None."""
    if not exc_info or exc_info is True or exc_info[0] is None:
        return None
    exc_type, exc_value, exc_tb = exc_info
    return {
        "type": exc_type.__name__ if exc_type else "",
        "message": str(exc_value) if exc_value else "",
        "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
    }

def _map_level(levelno: int) -> str:
    """Map logging level integer to snitchbot severity string."""
    if levelno >= logging.CRITICAL:
        return "critical"
    if levelno >= logging.ERROR:
        return "error"
    return "warning"


def _default_send(payload: dict) -> None:
    """Default send_event: forward via snitchbot.notify()."""
    import snitchbot

    # Pass the exception object (if any) so notify() includes the traceback.
    exc_obj = payload.get("_exc_value")  # BaseException | None

    snitchbot.notify(
        payload.get("text", ""),
        severity=payload.get("severity", "warning"),
        extras=payload.get("extras"),
        source=payload.get("source", "logging"),
        caller=payload.get("caller"),
        exc_info=exc_obj,
    )

class SnitchbotLoggingHandler(logging.Handler):
    """stdlib logging handler that forwards WARNING+ log records to sidecar.

    Args:
        send_event: Callable that accepts a single dict payload and sends it
                    to the sidecar. Defaults to snitchbot.notify().
        level:      Minimum logging level to forward. Clamped to WARNING from
                    below (L3, L4). Defaults to WARNING.
        disabled:   When True the handler accepts records but performs zero work
                    (L9 — zero-cost disabled mode).
    """

    def __init__(
        self,
        send_event: Callable[[dict], None] | None = None,
        level: int = logging.WARNING,
        disabled: bool = False,
    ) -> None:
        # Clamp: cannot forward anything below WARNING (L3, L4).
        if level < logging.WARNING:
            level = logging.WARNING
        super().__init__(level=level)
        self._send_event = send_event or _default_send
        self._disabled = disabled

    # ------------------------------------------------------------------
    # logging.Handler protocol
    # ------------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        """Forward *record* to sidecar if level passes filter.

        Never raises (L1). Uses thread-local guard to prevent recursion (L5).
        """
        # Zero-cost disabled mode (L9).
        if self._disabled:
            return

        # Level filter: handler.level already enforced by logging.Handler.handle(),
        # but emit() can be called directly in tests, so re-check.
        if record.levelno < self.level:
            return

        # Recursion guard (L5).
        if getattr(_in_handler, "active", False):
            return

        _in_handler.active = True
        try:
            self._forward(record)
        except Exception as exc:  # noqa: BLE001
            # Handler must never propagate exceptions to caller (L1).
            if __debug__:
                sys.stderr.write(f"[snitchbot] LoggingHandler error: {exc}\n")
        finally:
            _in_handler.active = False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _forward(self, record: logging.LogRecord) -> None:
        """Build payload dict and call send_event (L6, L7)."""
        # Extract the exception value from exc_info if available.
        # Pass it to _default_send so notify() can format the traceback.
        exc_value = None
        if record.exc_info and record.exc_info[1] is not None:
            exc_value = record.exc_info[1]

        payload: dict[str, Any] = {
            "text": record.getMessage(),
            "severity": _map_level(record.levelno),
            "source": "logging",
            "caller": {
                "file": record.pathname,
                "line": record.lineno,
                "func": record.funcName,
            },
            "extras": _extract_extras(record),
            "_exc_value": exc_value,
        }
        self._send_event(payload)
