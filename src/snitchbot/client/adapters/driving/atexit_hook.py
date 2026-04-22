"""atexit hook driving adapter.

Emits lifecycle/shutdown reason="clean_exit" when the process exits normally.

CI34: exactly one lifecycle shutdown emitted for clean exit
CI18: skipped if build_shutdown returns None (already sent by signal/excepthook)
"""
import atexit
import logging

logger = logging.getLogger("snitchbot.client.adapters.driving.atexit_hook")


def install(*, send_event, build_shutdown):
    """Register an atexit handler for clean process exit.

    Args:
        send_event: callable(event_dict) — sends event via IPC.
        build_shutdown: callable(reason=str) -> dict|None — builds shutdown event,
            returns None if already sent (CI18 dedup via _sent_shutdown_event).
    """
    def _on_exit():
        try:
            shutdown = build_shutdown(reason="clean_exit")
            if shutdown is None:
                return  # CI18: already sent — skip
            try:
                send_event(shutdown)
            except Exception:
                logger.debug("atexit: send_event failed", exc_info=True)
        except Exception:
            logger.debug("atexit: build_shutdown failed", exc_info=True)

    atexit.register(_on_exit)
