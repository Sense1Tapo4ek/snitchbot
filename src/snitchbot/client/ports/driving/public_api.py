"""Public API driving port: init(), notify(), watch_slow, request_context.

This is the singleton composition root for the client side.
Module-level state is an acknowledged exception to immutability (spec §0.3, P3/P4).

Spec:
- docs/superpowers/specs/2026-04-11-public-api-design.md §2–§4, §11 (P1–P8)
- docs/superpowers/specs/2026-04-11-client-internals-design.md §9, §10

Invariants:
- P1: notify() never raises
- P2: thread-safe via _init_lock
- P3: stats.called_before_init incremented on notify() before init()
- P4: SNITCHBOT_DISABLED=1 -> zero setup
- P7: idempotent on same config
- P8: init() raises on bad args (validation errors only)
- I2: runtime errors -> degraded, no raise
- CI33: startup lifecycle event sent last (before marking _initialized=True)
- CI37: os.register_at_fork(after_in_child=_after_fork_in_child) called once in init()
- CI38: _after_fork_in_child resets state and reinits
- CI40: _stored_config saved for fork reinit
"""
import logging
import os
import sys
import threading
import time

from snitchbot import __version__
from snitchbot.client.app.use_cases.initialize_client_uc import InitializeClientUseCase
from snitchbot.client.app.use_cases.send_event_uc import SendEventUseCase
from snitchbot.client.domain.stats_vo import ClientStats
from snitchbot.client.ports.driven.discovery.socket_path_service import SocketPathDiscovery
from snitchbot.client.ports.driven.spawner.subprocess_spawner import SubprocessSidecarSpawner
from snitchbot.client.ports.driven.transport.unix_dgram_transport import UnixDgramTransport

logger = logging.getLogger("snitchbot.client")


_stats: ClientStats = ClientStats()

_initialized: bool = False
_initialized_pid: int | None = None
_init_lock: threading.Lock = threading.Lock()
_stored_config: dict | None = None
_send_event_fn = None  # set during _init_impl; callable(dict) | None


def init(
    service: str,
    *,
    token: str | None = None,
    chat_id: str | int | None = None,
    anomaly=None,
    disabled: bool = False,
    role: str = "standalone",
    live_dashboard: bool = True,
    sample_interval_sec: int = 5,
    chart_width: int = 35,
    forum: bool | str = "auto",
    topic_color: int | None = None,
) -> None:
    """Initialize snitchbot. The only public function that may raise (P8).

    Raises ValueError for invalid args.
    Raises OSError for socket errors.
    Raises NotImplementedError on unsupported platform.
    Runtime errors -> degraded mode, no raise (I2).
    """
    global _initialized, _initialized_pid, _stored_config, _send_event_fn

    # 1. Kill-switch checks (P4 — zero setup)
    if disabled:
        return
    if os.environ.get("SNITCHBOT_DISABLED", "").lower() in ("1", "true", "yes"):
        return

    # Resolve token/chat_id: explicit args -> env vars -> .env file
    if token is None or chat_id is None:
        from snitchbot.config import SnitchbotConfig
        try:
            cfg = SnitchbotConfig()  # reads from env + .env
        except Exception:
            cfg = None
        if token is None:
            resolved_token = cfg.token if cfg else ""
        else:
            resolved_token = token
        if chat_id is None:
            resolved_chat_id: str | int = cfg.chat_id if cfg else ""
        else:
            resolved_chat_id = chat_id
    else:
        resolved_token = token
        resolved_chat_id = chat_id

    # 2. Validate args BEFORE touching any state (P8 — may raise)
    _validate_args(service, resolved_token, resolved_chat_id)
    if not isinstance(sample_interval_sec, int) or not (1 <= sample_interval_sec <= 60):
        raise ValueError(
            f"sample_interval_sec must be int in [1, 60], got {sample_interval_sec!r}"
        )
    # F1: forum mode validation
    if not (isinstance(forum, bool) or forum == "auto"):
        raise ValueError(f"forum must be True, False, or 'auto', got {forum!r}")
    if topic_color is not None:
        from snitchbot.sidecar.telegram_io.domain.services.topic_color_service import (
            TOPIC_COLOR_PALETTE,
        )
        if topic_color not in TOPIC_COLOR_PALETTE:
            raise ValueError(
                f"topic_color {topic_color!r} not in Telegram palette {TOPIC_COLOR_PALETTE}"
            )

    # Log estimated vitals cache size (client-side visibility)
    import math as _math

    from snitchbot.shared.domain.anomaly_config_vo import resolve_anomaly_param
    _resolved_ac = resolve_anomaly_param(anomaly)
    _max_hist_sec = _resolved_ac.max_history_seconds()
    _maxlen = max(60, _math.ceil(_max_hist_sec / sample_interval_sec) + 1)
    _est_bytes = _maxlen * 120
    if _est_bytes >= 1024 * 1024:
        _est_str = f"{_est_bytes / (1024 * 1024):.1f} MB"
    else:
        _est_str = f"{_est_bytes / 1024:.0f} KB"
    logger.warning(
        "snitchbot vitals cache: %d samples × %ds = %ds history, ~%s",
        _maxlen, sample_interval_sec, _maxlen * sample_interval_sec, _est_str,
    )

    with _init_lock:  # P2: thread safety
        # 3. Idempotency check (P7)
        if _initialized and _initialized_pid == os.getpid():
            if _matches_stored_config(service, resolved_token, resolved_chat_id):
                return  # P7: same config, no-op
            _stats.init_conflict += 1
            return  # §3.2: different config, keep first

        # 4. Save config for fork reinit (CI40) — before any side effects
        _stored_config = dict(
            service=service,
            token=resolved_token,
            chat_id=resolved_chat_id,
            anomaly=anomaly,
            role=role,
            sample_interval_sec=sample_interval_sec,
        )

        # 4b. Propagate live_dashboard setting to sidecar via env var
        if not live_dashboard:
            os.environ["SNITCHBOT_LIVE_DASHBOARD"] = "false"

        # 4c. Propagate sample_interval_sec to sidecar via env var
        if sample_interval_sec != 5:
            os.environ["SNITCHBOT_SAMPLE_INTERVAL_SEC"] = str(sample_interval_sec)

        # 4d. Propagate chart_width to sidecar via env var
        if chart_width != 35:
            os.environ["SNITCHBOT_CHART_WIDTH"] = str(chart_width)

        # 4e. Propagate forum + topic_color to sidecar via env vars (F1)
        if forum is True:
            os.environ["SNITCHBOT_FORUM"] = "true"
        elif forum is False:
            os.environ["SNITCHBOT_FORUM"] = "false"
        # "auto" -> leave unset; sidecar default is "auto"
        if topic_color is not None:
            os.environ["SNITCHBOT_TOPIC_COLOR"] = str(topic_color)

        # 5. Runtime init — may fail, never raises to caller (I2)
        try:
            _init_impl(
                service=service,
                token=resolved_token,
                chat_id=resolved_chat_id,
                anomaly=anomaly,
                role=role,
            )
        except Exception:
            logger.debug("init: _init_impl failed, entering degraded mode", exc_info=True)
            _stats.internal_errors += 1
            # Degraded mode — fall through and mark initialized

        # 7. Mark initialized (CI33: lifecycle startup happens inside _init_impl as last step)
        _initialized = True
        _initialized_pid = os.getpid()

        # 6. Register fork hook (CI37) — only after successful init
        try:
            os.register_at_fork(after_in_child=_after_fork_in_child)
        except AttributeError:
            # os.register_at_fork not available on Windows
            pass


def notify(
    text: str,
    *,
    severity: str = "warning",
    extras: dict | None = None,
    exc_info: bool | BaseException | None = None,
    source: str | None = None,
    caller: dict | None = None,
) -> None:
    """Send a custom notification. Never raises (P1)."""
    if not _initialized:
        _stats.called_before_init += 1  # P3
        return

    try:
        _do_notify(
            text, severity=severity, extras=extras,
            exc_info=exc_info, source=source, caller=caller,
        )
    except Exception:
        logger.debug("notify internal error", exc_info=True)
        _stats.internal_errors += 1


def _do_notify(
    text: str,
    *,
    severity: str,
    extras: dict | None,
    exc_info: bool | BaseException | None,
    source: str | None,
    caller: dict | None,
) -> None:
    """Inner notify — may raise; all callers wrap in try/except."""
    # Resolve exc_info
    attached_exc = None
    if exc_info is True:
        ei = sys.exc_info()
        if ei[0] is None:
            # Outside except block (NA4)
            _stats.notify_exc_info_no_exception += 1
            # Continue without exception attachment
        else:
            attached_exc = ei[1]
    elif isinstance(exc_info, BaseException):
        attached_exc = exc_info

    # Use provided caller, or extract from exception traceback, or frame inspection
    if caller is None and attached_exc is not None and attached_exc.__traceback__ is not None:
        # Walk to the deepest frame — that's where the exception was raised
        tb = attached_exc.__traceback__
        while tb.tb_next is not None:
            tb = tb.tb_next
        caller = {
            "file": tb.tb_frame.f_code.co_filename,
            "line": tb.tb_lineno,
            "func": tb.tb_frame.f_code.co_name,
        }
    if caller is None:
        try:
            frame = sys._getframe(2)
            caller = {
                "file": frame.f_code.co_filename,
                "line": frame.f_lineno,
                "func": frame.f_code.co_name,
            }
        except Exception:
            logger.debug("frame inspection failed", exc_info=True)

    from snitchbot.client.adapters.driving.instrumentation.request_context import (
        get_current_context,
    )
    ctx = get_current_context()
    trace_id = ctx.get("trace_id") if ctx is not None else None

    # Build exception payload with traceback if available
    exc_payload = None
    if attached_exc is not None:
        import traceback as _tb
        exc_payload = {
            "type": type(attached_exc).__name__,
            "message": str(attached_exc),
            "traceback": "".join(
                _tb.format_exception(
                    type(attached_exc), attached_exc, attached_exc.__traceback__,
                )
            ),
        }

    event: dict = {
        "v": __version__,
        "ts": time.time(),
        "kind": "custom",
        "severity": severity,
        "pid": os.getpid(),
        "trace_id": trace_id,
        "context": ctx,
        "payload": {
            "text": text,
            "extras": extras,
            "exception": exc_payload,
            "source": source,
            "caller": caller,
        },
    }

    if _send_event_fn is not None:
        _send_event_fn(event)


def _init_impl(
    *,
    service: str,
    token: str,
    chat_id: str | int,
    anomaly=None,
    role: str = "standalone",
) -> None:
    """Runtime initialization: transport, hooks, lifecycle.

    Called inside _init_lock. May raise — callers wrap in try/except.
    Follows spec §9 order:
    1. sys.excepthook
    2. threading.excepthook
    3. asyncio patch
    4. signal handlers (if main thread)
    5. atexit
    6. watchdog thread
    7. lifecycle startup event (CI33 — last step before marking _initialized)
    """
    global _send_event_fn

    from snitchbot.client.adapters.driving.atexit_hook import install as install_atexit
    from snitchbot.client.adapters.driving.excepthooks.asyncio_patch import (
        install as install_asyncio,
    )
    from snitchbot.client.adapters.driving.excepthooks.sys_excepthook import (
        install as install_sys_hook,
    )
    from snitchbot.client.adapters.driving.excepthooks.threading_excepthook import (
        install as install_threading_hook,
    )
    from snitchbot.client.adapters.driving.signals.signal_handlers import install as install_signals
    from snitchbot.client.domain.services.crash_classification_service import (
        classify_crash_severity,
    )
    from snitchbot.client.domain.services.lifecycle_service import (
        build_shutdown_event,
        build_startup_event,
    )
    from snitchbot.client.ports.driven.stack.stack_extraction_repo import extract_stack_frames

    def _noop_send(event: dict) -> None:
        """Fallback send when transport not ready (degraded mode)."""
        pass

    # Use noop send until transport is wired below
    _send_event_fn = _noop_send

    def _send(event: dict) -> None:
        fn = _send_event_fn
        if fn is not None:
            try:
                fn(event)
            except Exception:
                logger.debug("send_event error", exc_info=True)
                _stats.internal_errors += 1

    def _extract(tb) -> list[dict]:
        """Extract stack frames and convert StackFrame VOs to msgpack-friendly dicts."""
        return [
            {
                "file": f.file,
                "line": f.line,
                "func": f.func,
                "code": f.code,
                "is_user_code": f.is_user_code,
            }
            for f in extract_stack_frames(tb)
        ]

    # 1. sys.excepthook
    install_sys_hook(
        send_event=_send,
        classify_severity=classify_crash_severity,
        extract_stack=_extract,
        build_shutdown=build_shutdown_event,
    )

    # 2. threading.excepthook
    install_threading_hook(
        send_event=_send,
        classify_severity=classify_crash_severity,
        extract_stack=_extract,
    )

    # 2.5 Watchdog pre-wiring — create shared state BEFORE asyncio patch so
    # every instrumented loop can bind its pinger to the same last_alive (CI9).
    from snitchbot.client.adapters.driving.watchdog.pinger_coroutine import LastAlive
    from snitchbot.client.adapters.driving.watchdog.watchdog_thread import WatchdogThread
    from snitchbot.shared.domain.anomaly_config_vo import AnomalyConfig, resolve_anomaly_param

    # Resolve anomaly config to extract WatchdogConfig
    resolved_anomaly = resolve_anomaly_param(anomaly)
    watchdog_cfg = (
        resolved_anomaly.watchdog
        if isinstance(resolved_anomaly, AnomalyConfig)
        else None
    )

    _last_alive = LastAlive()
    _watchdog = WatchdogThread(
        last_alive=_last_alive,
        send_event=_send,
        loop=None,  # attached when asyncio patch instruments a loop
        watchdog_config=watchdog_cfg,
    )

    # 3. asyncio patch (monkey-patch + lazy-bind, schedules pinger)
    install_asyncio(
        send_event=_send,
        classify_severity=classify_crash_severity,
        extract_stack=_extract,
        last_alive=_last_alive,
        watchdog=_watchdog,
    )

    # 4. signal handlers (silent skip if not main thread, CI16)
    install_signals(
        send_event=_send,
        build_shutdown=build_shutdown_event,
    )

    # 5. atexit hook
    install_atexit(
        send_event=_send,
        build_shutdown=build_shutdown_event,
    )

    # 7. Wire real transport (before lifecycle event so startup is delivered)
    from snitchbot.shared.adapters.driven.codec.msgpack_codec import MsgpackCodec

    discovery = SocketPathDiscovery()
    transport = UnixDgramTransport()
    spawner = SubprocessSidecarSpawner()

    init_uc = InitializeClientUseCase(
        _discovery=discovery,
        _transport=transport,
        _spawner=spawner,
        _stats=_stats,
    )

    init_uc(
        service=service,
        token=token,
        chat_id=chat_id,
        anomaly_config=anomaly,
        role=role,
    )

    codec = MsgpackCodec()
    send_uc = SendEventUseCase(
        _transport=transport,
        _codec=codec,
        _stats=_stats,
    )

    _send_event_fn = send_uc

    # 7. Wire watch_slow production send
    from snitchbot.client.adapters.driving.instrumentation import watch_slow as _ws_mod
    _ws_mod._module_send_event = _send

    # 7.5 Start the watchdog daemon thread now that _send is real.
    _watchdog.start()

    # 7.6 If an event loop is already running in this thread (e.g. user
    # called init() from inside async code), instrument it right away so the
    # pinger starts without waiting for the next asyncio.run().
    try:
        import asyncio as _asyncio
        _running_loop = _asyncio.get_running_loop()
    except RuntimeError:
        _running_loop = None
    if _running_loop is not None:
        from snitchbot.client.adapters.driving.excepthooks.asyncio_patch import (
            instrument_loop as _instrument_loop,
        )
        try:
            _instrument_loop(
                _running_loop,
                send_event=_send,
                classify_severity=classify_crash_severity,
                extract_stack=_extract,
            )
        except Exception:
            logger.debug("instrument_loop failed for running loop", exc_info=True)

    # 8. Lifecycle startup event (CI33 — must be last)
    startup_event = build_startup_event(service=service, role=role)
    _send(startup_event)


def _after_fork_in_child() -> None:
    """Called in child process after os.fork().

    Resets initialized state and reinits from _stored_config.
    CI38: compares _initialized_pid with current getpid().
    """
    global _initialized, _initialized_pid, _send_event_fn

    # If _initialized_pid is None — never initialized, nothing to do
    if _initialized_pid is None:
        return

    # If pid matches — this is the parent's hook firing in parent (shouldn't happen
    # normally, but guard against it)
    if _initialized_pid == os.getpid():
        return

    # We're in the child — reset state
    _initialized = False
    _send_event_fn = None

    # Close inherited transport resources
    # (noop here — transport close is handled by the transport itself on next send)

    # Reset lifecycle state so child can send its own startup event (CI38)
    from snitchbot.client.domain.services import lifecycle_service
    lifecycle_service.reset_lifecycle_state()

    # Reinit with stored config (CI40)
    if _stored_config is not None:
        try:
            _init_impl(**_stored_config)
            _initialized = True
            _initialized_pid = os.getpid()
        except Exception:
            # Reinit failed — stay in uninitialized state (best-effort)
            logger.debug("fork reinit failed", exc_info=True)


def _validate_args(service: str, token: str, chat_id: str | int) -> None:
    """Validate init() arguments. Raises ValueError on bad input (P8, §3.3)."""
    if not isinstance(service, str) or not service.strip():
        raise ValueError(f"service must be a non-empty string, got: {service!r}")

    if not token or not isinstance(token, str):
        raise ValueError("token must be a non-empty string (or set SNITCHBOT_TOKEN env var)")

    # chat_id must be convertible to int
    try:
        int(str(chat_id).strip())
    except (ValueError, TypeError) as err:
        raise ValueError(
            f"chat_id must be an integer or integer string, got: {chat_id!r}"
        ) from err


def _matches_stored_config(service: str, token: str, chat_id: str | int) -> bool:
    """Return True if args match the stored config (P7 idempotency check)."""
    if _stored_config is None:
        return False
    return (
        _stored_config.get("service") == service
        and _stored_config.get("token") == token
        and str(_stored_config.get("chat_id", "")) == str(chat_id)
    )
