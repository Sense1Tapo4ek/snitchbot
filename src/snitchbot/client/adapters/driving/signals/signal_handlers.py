"""Signal handlers driving adapter.

Translates SIGTERM/SIGINT into lifecycle/shutdown events.

CI16: only installed from main thread (signal.signal raises ValueError otherwise)
CI17: SIGTERM emits lifecycle shutdown reason="sigterm"
CI18: build_shutdown returns None if already sent — dedup handled by caller
CI19: SIGHUP not installed
"""
import logging
import os
import signal

logger = logging.getLogger("snitchbot.client.adapters.driving.signals")

_previous_sigterm = None
_previous_sigint = None


def install(*, send_event, build_shutdown):
    """Install SIGTERM and SIGINT handlers.

    Silently skipped if called from a non-main thread (CI16).

    Args:
        send_event: callable(event_dict) — sends event via IPC.
        build_shutdown: callable(reason=str) -> dict|None — builds shutdown event,
            returns None if already sent (CI18 dedup).
    """
    global _previous_sigterm, _previous_sigint

    def _make_handler(signum_name):
        def handler(signum, frame):
            reason = "sigterm" if signum == signal.SIGTERM else "sigint"
            try:
                shutdown = build_shutdown(reason=reason)
                if shutdown is not None:
                    send_event(shutdown)
            except Exception:
                logger.debug("signal handler error", exc_info=True)

            # Chain to previous handler
            prev = _previous_sigterm if signum == signal.SIGTERM else _previous_sigint
            if callable(prev):
                prev(signum, frame)
            elif prev in (signal.SIG_DFL, None):
                # Restore default and re-raise — causes process to die from the signal
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)
            # SIG_IGN: do nothing

        return handler

    try:
        _previous_sigterm = signal.signal(signal.SIGTERM, _make_handler("SIGTERM"))
        _previous_sigint = signal.signal(signal.SIGINT, _make_handler("SIGINT"))
    except ValueError:
        # signal.signal() only works from main thread — silently skip (CI16)
        logger.debug("signal registration skipped (not main thread)")


def uninstall():
    """Restore the original SIGTERM and SIGINT handlers."""
    global _previous_sigterm, _previous_sigint
    if _previous_sigterm is not None:
        signal.signal(signal.SIGTERM, _previous_sigterm)
        _previous_sigterm = None
    if _previous_sigint is not None:
        signal.signal(signal.SIGINT, _previous_sigint)
        _previous_sigint = None
