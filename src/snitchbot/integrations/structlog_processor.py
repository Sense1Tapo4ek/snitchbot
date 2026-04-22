"""structlog processor that forwards WARNING+ events to snitchbot sidecar.

"""
import sys
import threading
from collections.abc import Callable
from typing import Any

__all__ = ["make_structlog_processor", "structlog_processor"]


# structlog meta keys added by built-in processors — not user extras (§5.2).
_STRUCTLOG_META_KEYS: frozenset[str] = frozenset(
    [
        "event",
        "level",
        "timestamp",
        "logger",
        "filename",
        "lineno",
        "func_name",
        "module",
        "process",
        "thread",
        "pathname",
        "exception",
        "exc_info",
        "stack_info",
    ]
)

# Levels that are forwarded (L3 — DEBUG and INFO are never forwarded).
_FORWARD_LEVELS: frozenset[str] = frozenset(["warning", "error", "critical"])

# Thread-local recursion guard shared across all processor instances (L5).
_in_processor = threading.local()


def _extract_extras(event_dict: dict) -> dict[str, Any]:
    """Return user-supplied keys from structlog event_dict (§5.2)."""
    return {
        k: v
        for k, v in event_dict.items()
        if k not in _STRUCTLOG_META_KEYS and not k.startswith("_")
    }

def _build_caller(event_dict: dict) -> dict[str, Any] | None:
    """Extract caller info from CallsiteParameterAdder keys (§5.2)."""
    # Prefer pathname (full path) over filename (basename)
    filepath = event_dict.get("pathname") or event_dict.get("filename")
    lineno = event_dict.get("lineno")
    func_name = event_dict.get("func_name")
    if filepath is None and lineno is None and func_name is None:
        return None
    return {"file": filepath, "line": lineno, "func": func_name}


def _default_send(payload: dict) -> None:
    """Default send_event: forward via snitchbot.notify()."""
    import snitchbot

    exc_obj = payload.get("_exc_value")
    caller = payload.get("caller")  # from CallsiteParameterAdder or None

    snitchbot.notify(
        payload.get("text", ""),
        severity=payload.get("severity", "warning"),
        extras=payload.get("extras"),
        source=payload.get("source", "structlog"),
        caller=caller,
        exc_info=exc_obj,
    )

def make_structlog_processor(
    send_event: Callable[[dict], None] | None = None,
) -> Any:
    """Return a structlog-compatible processor that forwards WARNING+ events.

    The returned callable is a standard structlog processor with signature::

        processor(logger, method_name, event_dict) -> event_dict

    It returns *event_dict* unchanged (L2 — pure passthrough) and calls
    *send_event* as a side-effect for WARNING+ levels.

    Args:
        send_event: Callable that accepts a single dict payload. Defaults to
                    snitchbot.notify(). Must not be called at DEBUG/INFO
                    (L3). Errors from send_event are silently swallowed (L1).
    """
    resolved_send = send_event or _default_send

    def processor(logger: Any, method_name: str, event_dict: dict) -> dict:
        """structlog processor: passthrough + optional side-effect forward."""
        # Passthrough guard — always return event_dict regardless of path (L2).
        # Level filter (L3).
        if method_name not in _FORWARD_LEVELS:
            return event_dict

        # Recursion guard (L5).
        if getattr(_in_processor, "active", False):
            return event_dict

        _in_processor.active = True
        try:
            _forward(event_dict, method_name, resolved_send)
        except Exception as exc:  # noqa: BLE001
            # Processor must never propagate exceptions (L1).
            if __debug__:
                sys.stderr.write(f"[snitchbot] structlog_processor error: {exc}\n")
        finally:
            _in_processor.active = False

        return event_dict

    return processor


def _forward(
    event_dict: dict,
    method_name: str,
    send_event: Callable[[dict], None],
) -> None:
    """Build payload and call send_event (L6)."""
    # Caller info comes from CallsiteParameterAdder (if configured).
    # Without it, caller will be None — alerts won't show caller line.
    caller = _build_caller(event_dict)
    # Extract exception for traceback display.
    # structlog passes exc_info=True or exc_info=(type, value, tb).
    exc_value = None
    raw_exc_info = event_dict.get("exc_info")
    if raw_exc_info is True:
        import sys as _sys
        ei = _sys.exc_info()
        if ei[1] is not None:
            exc_value = ei[1]
    elif isinstance(raw_exc_info, tuple) and len(raw_exc_info) == 3:
        exc_value = raw_exc_info[1]
    elif isinstance(raw_exc_info, BaseException):
        exc_value = raw_exc_info

    payload: dict[str, Any] = {
        "text": event_dict.get("event", ""),
        "severity": method_name,  # "warning" / "error" / "critical"
        "source": "structlog",
        "caller": caller,
        "extras": _extract_extras(event_dict),
        "_exc_value": exc_value,
    }
    send_event(payload)

# Pre-built default processor instance — ready to use without calling the factory.
structlog_processor = make_structlog_processor()
