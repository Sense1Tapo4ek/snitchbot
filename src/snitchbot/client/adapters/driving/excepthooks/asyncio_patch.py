"""asyncio lazy-bind exception handler driving adapter.

Monkey-patches asyncio.events.new_event_loop and asyncio.new_event_loop so
every new loop gets a pinger scheduled. The pinger's first tick installs the
exception handler and keeps last_alive fresh for the watchdog thread.

CI4: asyncio exception handler installed via lazy-bind from pinger's first tick.
CI5: instrument_loop idempotent — second call on same loop is no-op.
CI9: pinger scheduled on every instrumented loop; watchdog reads last_alive.
CI36: asyncio handler does NOT emit lifecycle/shutdown event.
I9: handler swallows its own errors.
"""
import asyncio
import asyncio.events
import logging
from collections.abc import Callable

from .asyncio_handler import build_asyncio_crash_event

logger = logging.getLogger("snitchbot.client.adapters.driving.excepthooks.asyncio_patch")

_original_new_event_loop = None
_INSTRUMENT_SENTINEL = "_snitchbot_instrumented"

# Module-level refs captured at install() time, used by instrument_loop() so
# every (patched or explicit) loop gets a pinger bound to the same last_alive.
_last_alive_ref = None
_watchdog_ref = None


def install(
    *,
    send_event: Callable,
    classify_severity: Callable,
    extract_stack: Callable,
    last_alive=None,
    watchdog=None,
) -> None:
    """Monkey-patch asyncio.events.new_event_loop and asyncio.new_event_loop.

    Every new loop will have a pinger scheduled that installs the asyncio
    exception handler on its first tick and updates ``last_alive`` so the
    watchdog thread can detect event-loop blocks (CI9).

    Patches both asyncio.events.new_event_loop (for direct importers) and
    asyncio.new_event_loop (the public API used by most callers).

    Args:
        send_event: callable(event_dict) — sends event via IPC.
        classify_severity: callable(exc_type) -> str — returns severity string.
        extract_stack: callable(exc_tb) -> list[dict] — extracts stack frames.
        last_alive: shared LastAlive container the pinger updates (CI9/CI15).
        watchdog: WatchdogThread instance; its ``_loop`` attribute is set the
            first time a loop is instrumented so snapshot collection works.
    """
    global _original_new_event_loop, _last_alive_ref, _watchdog_ref
    _original_new_event_loop = asyncio.events.new_event_loop
    _last_alive_ref = last_alive
    _watchdog_ref = watchdog

    def patched_new_event_loop():
        loop = _original_new_event_loop()
        instrument_loop(
            loop,
            send_event=send_event,
            classify_severity=classify_severity,
            extract_stack=extract_stack,
        )
        return loop

    asyncio.events.new_event_loop = patched_new_event_loop
    asyncio.new_event_loop = patched_new_event_loop


def instrument_loop(
    loop,
    *,
    send_event: Callable,
    classify_severity: Callable,
    extract_stack: Callable,
) -> None:
    """Instrument an existing loop. Idempotent (CI5).

    Called explicitly for already-running loops (e.g., uvicorn/uvloop)
    or any loop created outside the asyncio.new_event_loop path.

    Attaches:
    1. Exception handler (CI4)
    2. Pinger task that keeps last_alive fresh (CI9)
    3. Watchdog loop reference so _collect_snapshot can dispatch snapshots.

    Args:
        loop: asyncio event loop to instrument.
        send_event: callable(event_dict) — sends event via IPC.
        classify_severity: callable(exc_type) -> str — returns severity string.
        extract_stack: callable(exc_tb) -> list[dict] — extracts stack frames.
    """
    if getattr(loop, _INSTRUMENT_SENTINEL, False):
        return  # CI5: already instrumented — no-op
    setattr(loop, _INSTRUMENT_SENTINEL, True)

    # Attach the loop to the watchdog so snapshot collection (CI12) works.
    if _watchdog_ref is not None:
        try:
            _watchdog_ref._loop = loop
        except Exception:
            logger.debug("watchdog loop attach failed", exc_info=True)

    def _bootstrap() -> None:
        _install_handler(loop, send_event, classify_severity, extract_stack)
        _schedule_pinger(loop)

    # call_soon works whether or not the loop is running.
    if loop.is_running():
        loop.call_soon_threadsafe(_bootstrap)
    else:
        loop.call_soon(_bootstrap)


def _schedule_pinger(loop) -> None:
    """Create the pinger task on the loop if last_alive was provided.

    Must be called from inside the loop thread.
    """
    if _last_alive_ref is None:
        return
    try:
        from snitchbot.client.adapters.driving.watchdog.pinger_coroutine import pinger
        loop.create_task(pinger(last_alive=_last_alive_ref), name="snitchbot-pinger")
    except Exception:
        logger.debug("pinger task creation failed", exc_info=True)


def _install_handler(
    loop,
    send_event: Callable,
    classify_severity: Callable,
    extract_stack: Callable,
) -> None:
    """Install asyncio exception handler on the loop (CI4).

    Chains to the previously installed handler (or the default).
    """
    _prev_handler = loop.get_exception_handler()

    def handler(loop, context):
        try:
            exc = context.get("exception")
            if exc is not None:
                severity = classify_severity(type(exc))
                event = build_asyncio_crash_event(exc, severity, extract_stack)
                send_event(event)
        except Exception:
            # I9: swallow handler's own errors
            logger.debug("asyncio exception handler error", exc_info=True)

        # Chain: call previous handler or fall through to default
        if _prev_handler is not None:
            _prev_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(handler)


def uninstall() -> None:
    """Restore original asyncio.events.new_event_loop and asyncio.new_event_loop."""
    global _original_new_event_loop
    if _original_new_event_loop is not None:
        asyncio.events.new_event_loop = _original_new_event_loop
        asyncio.new_event_loop = _original_new_event_loop
        _original_new_event_loop = None
