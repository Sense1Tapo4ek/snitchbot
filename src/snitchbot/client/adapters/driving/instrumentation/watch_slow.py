"""watch_slow decorator — driving adapter for slow-call instrumentation.

Measures function execution time and emits a slow_call event if it exceeds
threshold_ms.

Spec:
    docs/superpowers/specs/2026-04-11-client-internals-design.md §6
    docs/superpowers/specs/2026-04-11-public-api-design.md §5

Invariants:
    CI21: @watch_slow(1000) raises ValueError (positional not allowed);
          detects async via inspect.iscoroutinefunction
    CI22: uses time.monotonic(), not wall clock
    CI23: sends event on completion even if function raises
    CI24: functools.wraps preserves metadata
    CI25: fast path — no event if duration < threshold
    CI26: qualname captured at decoration time, not call time
"""
import functools
import inspect
import os
import time
from collections.abc import Callable
from typing import Any

from snitchbot import __version__

# Module-level send_event callable. Set during init().
# Tests inject their own via the send_event parameter.
_module_send_event: Callable[[dict], None] | None = None


def _default_send(event: dict) -> None:  # pragma: no cover
    """Fallback: forward to module-level _module_send_event if set."""
    if _module_send_event is not None:
        _module_send_event(event)


def watch_slow(
    *args: Any,
    threshold_ms: int,
    send_event: Callable[[dict], None] | None = None,
) -> Callable:
    """Decorator factory.

    Args:
        threshold_ms: Keyword-only positive integer milliseconds threshold.
            Positional usage (@watch_slow(1000)) raises ValueError.
        send_event: Optional callable for injecting the event sender in tests.
            If None, falls back to module-level _module_send_event.

    Returns:
        A decorator that wraps sync or async functions.

    Raises:
        ValueError: If threshold_ms is not a positive int, or if called
            positionally.
    """
    # CI21: positional args are forbidden — @watch_slow(1000) must raise.
    if args:
        raise ValueError(
            "watch_slow() requires keyword-only argument: "
            "@watch_slow(threshold_ms=1000), not @watch_slow(1000)"
        )

    if not isinstance(threshold_ms, int) or isinstance(threshold_ms, bool):
        raise ValueError(
            f"threshold_ms must be a positive int, got {threshold_ms!r}"
        )
    if threshold_ms <= 0:
        raise ValueError(
            f"threshold_ms must be a positive int, got {threshold_ms!r}"
        )

    threshold_sec = threshold_ms / 1000.0
    _send = send_event if send_event is not None else _default_send

    def decorator(fn: Callable) -> Callable:
        # CI26: capture qualname and location once at decoration time.
        qualname = f"{fn.__module__}.{fn.__qualname__}"
        location = _get_func_location(fn)
        is_async = inspect.iscoroutinefunction(fn)  # CI21: use inspect, not asyncio

        def _emit(duration_sec: float) -> None:
            if duration_sec >= threshold_sec:  # CI25: fast path skips emit
                from snitchbot.client.adapters.driving.instrumentation.request_context import (
                    get_current_context,
                )
                ctx = get_current_context()
                trace_id = ctx.get("trace_id") if ctx is not None else None
                _send(
                    {
                        "v": __version__,
                        "ts": time.time(),
                        "kind": "slow_call",
                        "severity": "warning",
                        "pid": os.getpid(),
                        "trace_id": trace_id,
                        "context": ctx,
                        "payload": {
                            "func_qualname": qualname,
                            "duration_ms": int(duration_sec * 1000),
                            "threshold_ms": threshold_ms,
                            "is_async": is_async,
                            "location": location,
                        },
                    }
                )

        if is_async:
            @functools.wraps(fn)  # CI24
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                start = time.monotonic()  # CI22
                try:
                    return await fn(*args, **kwargs)
                finally:
                    _emit(time.monotonic() - start)  # CI23: always in finally

            return async_wrapper
        else:
            @functools.wraps(fn)  # CI24
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                start = time.monotonic()  # CI22
                try:
                    return fn(*args, **kwargs)
                finally:
                    _emit(time.monotonic() - start)  # CI23: always in finally

            return sync_wrapper

    return decorator


def _get_func_location(fn: Callable) -> dict:
    """Extract file + first line from a function's code object."""
    try:
        return {
            "file": fn.__code__.co_filename,
            "line": fn.__code__.co_firstlineno,
        }
    except AttributeError:
        return {"file": "unknown", "line": 0}
