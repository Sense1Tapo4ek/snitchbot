"""Sidecar entrypoint: python -m snitchbot.sidecar

Reads config from env vars (set by SubprocessSidecarSpawner).
Binds UNIX DGRAM socket, runs async event loop with:
  - RecvLoop: receive client events
  - DispatchLoop: periodic tick -> dedup -> rate-limit -> Telegram
  - IdleWatcher: exit after 30s idle
  - VitalsSampler: sample process vitals every 5s
  - LiveMessageUpdater: update live dashboard every 10s
  - EditFlusher: flush pending dedup edits every 2s
  - Signal handler: SIGTERM/SIGINT -> graceful shutdown
"""
import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

from snitchbot.config import SnitchbotConfig
from snitchbot.shared.adapters.driven.codec.msgpack_codec import MsgpackCodec
from snitchbot.shared.domain import RecentEvent
from snitchbot.shared.domain.services import compute_config_hash
from snitchbot.shared.domain.services import compute_fingerprint
from snitchbot.sidecar.anomalies.app.workflows.vitals_sampler_workflow import VitalsSamplerWorkflow
from snitchbot.sidecar.anomalies.ports.driven.psutil_vitals_sampler import PsutilVitalsSampler
from snitchbot.sidecar.ingest.adapters.driving.recv_loop import RecvLoop
from snitchbot.sidecar.ingest.app.use_cases.register_client_uc import RegisterClientUseCase
from snitchbot.sidecar.ingest.domain.client_registry_agg import ClientRegistry
from snitchbot.sidecar.ingest.ports.driven.listening_socket import ListeningSocket
from snitchbot.sidecar.interactive.app.use_cases.last_query import LastQuery
from snitchbot.sidecar.interactive.app.use_cases.status_query import StatusQuery
from snitchbot.sidecar.interactive.app.use_cases.test_uc import TestUC
from snitchbot.sidecar.interactive.app.use_cases.trace_callback_uc import TraceCallbackUC
from snitchbot.sidecar.interactive.domain.recent_events_buffer_agg import RecentEventsBuffer
from snitchbot.sidecar.live_message.app.workflows.live_message_updater_workflow import (
    LiveMessageUpdaterWorkflow,
)
from snitchbot.sidecar.live_message.domain.live_message_state_agg import LiveMessageState
from snitchbot.sidecar.muting.app.use_cases.mute_callback_uc import MuteCallbackUC
from snitchbot.sidecar.muting.app.use_cases.mute_uc import MuteUC
from snitchbot.sidecar.muting.app.use_cases.unmute_callback_uc import UnmuteCallbackUC
from snitchbot.sidecar.muting.app.use_cases.unmute_uc import UnmuteUC
from snitchbot.sidecar.muting.domain.mute_state_agg import MuteState
from snitchbot.sidecar.muting.ports.driven.persistence.mute_repo_json import MuteRepoJson
from snitchbot.sidecar.pipeline.app.workflows.dispatch_loop_workflow import DispatchLoopWorkflow
from snitchbot.sidecar.pipeline.app.workflows.edit_flusher_workflow import EditFlusherWorkflow
from snitchbot.sidecar.pipeline.domain.central_queue_agg import CentralQueue
from snitchbot.sidecar.pipeline.domain.dedup_cache_agg import DedupCache
from snitchbot.sidecar.pipeline.domain.rate_bucket_vo import RateBucket
from snitchbot.sidecar.pipeline.domain.services.enqueue_service import classify_and_enqueue
from snitchbot.sidecar.pipeline.domain.services.render_dispatch_service import render_dispatch
from snitchbot.sidecar.session.app.use_cases.tick_idle_watcher_uc import TickIdleWatcherUseCase
from snitchbot.sidecar.session.domain.session_agg import SidecarSession
from snitchbot.sidecar.telegram_io.adapters.driving.callback_router import CallbackRouter

# Interactive Telegram: commands + callbacks + long-polling
from snitchbot.sidecar.telegram_io.adapters.driving.command_router import CommandRouter
from snitchbot.sidecar.telegram_io.adapters.driving.long_polling_controller import (
    LongPollingController,
)
from snitchbot.sidecar.telegram_io.app.use_cases.set_commands_uc import SetCommandsUC
from snitchbot.sidecar.telegram_io.domain.command_budget_vo import CommandBudget
from snitchbot.sidecar.telegram_io.domain.meta_budget_vo import MetaBudget
from snitchbot.sidecar.telegram_io.ports.driven.tg_gateway_httpx import TgGatewayHttpx
from snitchbot.sidecar.telegram_io.ports.driving.telegram_io_facade import (
    TelegramIOFacade,
)

logger = logging.getLogger("snitchbot.sidecar")

from snitchbot import __version__ as _LIB_VERSION


def main() -> None:
    import threading as _threading

    # Install a threading-level shutdown flag early so SIGTERM before asyncio
    # event loop startup still results in a clean exit (exit code 0).
    _shutdown_requested = _threading.Event()

    def _early_sigterm(signum, frame):  # noqa: ANN001
        _shutdown_requested.set()

    signal.signal(signal.SIGTERM, _early_sigterm)
    signal.signal(signal.SIGINT, _early_sigterm)

    config = SnitchbotConfig.from_env()

    if config.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    sock_path = Path(config.socket_path)
    config_hash = compute_config_hash(config.token, config.chat_id)

    # --- Build components ---
    listening = ListeningSocket(sock_path)
    listening.bind()  # may raise SystemExit(0) on EADDRINUSE
    # Set a short timeout so recvfrom unblocks periodically — enables graceful shutdown
    if listening._sock is not None:
        listening._sock.settimeout(0.5)

    codec = MsgpackCodec()
    registry = ClientRegistry()
    session = SidecarSession(started_at=time.monotonic())
    queue = CentralQueue()
    dedup = DedupCache()
    rate_bucket = RateBucket()
    mute = MuteState()
    gateway = TgGatewayHttpx(token=config.token)
    stats: dict = {}

    # --- Interactive Telegram components ---
    recent_buffer = RecentEventsBuffer()
    cmd_budget = CommandBudget()
    meta_budget = MetaBudget()  # noqa: F841 — reserved for rate-limit notifications

    # Mute repo: domain-first async JSON persistence.
    # UCs call await mute_repo.save(mute_state) passing MuteState directly.
    mute_repo = MuteRepoJson(path=Path(config.socket_path).parent / "mutes.json")

    # Shared latency buffer for /test UC (last 10 sendMessage latencies)
    _latency_buffer: list[float] = []

    # --- Use cases that do NOT depend on the TelegramIOFacade ---
    mute_uc = MuteUC(
        _mute_state=mute,
        _mute_repo=mute_repo,
    )

    unmute_uc = UnmuteUC(
        _mute_state=mute,
        _mute_repo=mute_repo,
    )

    set_commands_uc = SetCommandsUC(
        _gateway=gateway,
        _chat_id=config.chat_id,
    )

    mute_cb_uc = MuteCallbackUC(
        _mute_state=mute,
        _mute_repo=mute_repo,
        _gateway=gateway,
        _chat_id=config.chat_id,
    )

    unmute_cb_uc = UnmuteCallbackUC(
        _mute_state=mute,
        _mute_repo=mute_repo,
        _gateway=gateway,
        _chat_id=config.chat_id,
    )

    trace_cb_uc = TraceCallbackUC(
        _dedup_cache=dedup,
        _gateway=gateway,
        _chat_id=config.chat_id,
    )

    callback_router = CallbackRouter(
        _mute_cb_uc=mute_cb_uc,
        _unmute_cb_uc=unmute_cb_uc,
        _trace_cb_uc=trace_cb_uc,
        _gateway=gateway,
        _chat_id=config.chat_id,
    )

    # Vitals / live message / edit flusher
    # registry.clients_dict is the single source of truth for all connected clients.
    # vitals_clients was removed — use registry.clients_dict directly.
    vitals_sampler = PsutilVitalsSampler()

    def _enqueue_anomaly(event: dict) -> None:
        """Route an internally-generated anomaly event through the dispatch
        pipeline — same enrichment steps as recv_loop._route for client events:
        fingerprint -> dedup classify -> enqueue with priority -> recent_buffer.
        """
        try:
            fp = compute_fingerprint(event)
            accepted, action, enriched = classify_and_enqueue(
                event=event,
                fingerprint=fp,
                dedup=dedup,
                queue=queue,
                now=time.monotonic(),
            )
            if accepted and recent_buffer is not None:
                payload = event.get("payload") or {}
                recent_buffer.add(RecentEvent(
                    ts=event.get("ts", 0.0),
                    fingerprint=fp,
                    severity=event.get("severity"),
                    exception_type=None,
                    message=payload.get("anomaly_type"),
                    pid=event.get("pid"),
                    kind=event.get("kind", "anomaly"),
                ))
        except Exception:
            logger.debug("anomaly enqueue failed", exc_info=True)

    vitals_workflow = VitalsSamplerWorkflow(
        _enqueue_anomaly=_enqueue_anomaly,
        _sampler=vitals_sampler,
        _sample_interval_sec=config.sample_interval_sec,
    )

    edit_flusher = EditFlusherWorkflow(_dedup_cache=dedup)

    register_uc = RegisterClientUseCase(
        _registry=registry,
        _session=session,
        _config_hash=config_hash,
    )

    def _on_client_killed(pid: int, service: str, role: str) -> None:
        """Goodbye protocol: emit a 'killed' lifecycle event for a PID
        that disappeared without sending a shutdown event."""
        killed_event = {
            "v": _LIB_VERSION,
            "ts": time.time(),
            "kind": "lifecycle",
            "severity": "warning",
            "pid": pid,
            "service": service,
            "trace_id": None,
            "context": None,
            "payload": {
                "phase": "shutdown",
                "reason": "killed",
                "exit_code": None,
                "role": role,
            },
        }
        _enqueue_anomaly(killed_event)

    idle_uc = TickIdleWatcherUseCase(
        _session=session,
        _registry=registry,
        _on_client_killed=_on_client_killed,
    )

    from functools import partial
    _render = partial(render_dispatch, service=config.sidecar_service)

    # --- Forum-mode wiring deferred to _run() ---------------------------
    # TelegramIOFacade needs forum-mode detection (async getChat/getMe/
    # getChatMember), so it and every component that takes it as a
    # dependency are built inside _run() after detection completes.
    # The following names are assigned inside _run() and captured via
    # closure below: telegram_io_facade, status_query, last_query,
    # test_uc, chart_query, export_query, command_router, long_polling,
    # dispatch, live_message.

    def _recv_enqueue_fn(event: dict, fingerprint: str | None) -> tuple[bool, str, dict]:
        """Composition-root binding: classify via dedup, enqueue as QueueItem."""
        accepted, action, enriched = classify_and_enqueue(
            event=event,
            fingerprint=fingerprint,
            dedup=dedup,
            queue=queue,
            now=time.monotonic(),
        )
        return accepted, action, enriched

    recv_loop = RecvLoop(
        socket=listening,
        codec=codec,
        register_uc=register_uc,
        registry=registry,
        queue=queue,
        stats=stats,
        enqueue_fn=_recv_enqueue_fn,
        fingerprint_fn=compute_fingerprint,
        session=session,
        recent_buffer=recent_buffer,
    )

    # --- Async main ---
    async def _run() -> None:
        shutdown_event = asyncio.Event()

        # If signal already arrived before event loop started, shut down immediately
        if _shutdown_requested.is_set():
            shutdown_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, shutdown_event.set)

        # Also poll the threading event in case signal arrives in a gap
        async def _poll_shutdown() -> None:
            while not shutdown_event.is_set():
                if _shutdown_requested.is_set():
                    shutdown_event.set()
                    break
                await asyncio.sleep(0.1)

        # ─── Per-service topics: auto-detect chat capabilities ───────────
        # Topics are activated iff the chat is a forum supergroup AND the bot
        # has `can_manage_topics`. Otherwise the sidecar sends every message
        # to the chat without a thread id (no degradation in functionality).
        from snitchbot.sidecar.telegram_io.app.use_cases.resolve_topic_uc import (
            ResolveTopicUseCase,
        )
        from snitchbot.sidecar.telegram_io.domain.forum_mode_vo import ForumModeVO
        from snitchbot.sidecar.telegram_io.domain.services.topic_registry_service import (
            TopicRegistry,
        )
        from snitchbot.sidecar.telegram_io.ports.driven.persistence.topic_store_json import (
            JsonFileTopicStore,
        )

        forum_mode = ForumModeVO(is_forum=False, can_manage_topics=None)
        try:
            chat = await gateway.get_chat(chat_id=config.chat_id)
            if bool(chat.get("is_forum", False)):
                me = await gateway.get_me()
                member = await gateway.get_chat_member(
                    chat_id=config.chat_id, user_id=int(me["id"]),
                )
                rights = bool(member.get("can_manage_topics", False))
                forum_mode = ForumModeVO(
                    is_forum=True,
                    can_manage_topics=rights,
                )
                if not rights:
                    logger.info(
                        "chat is a forum but bot lacks can_manage_topics — "
                        "sending all messages to the chat without per-service "
                        "topics.",
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "topic-capability detection failed: %r — sending all messages "
                "to the chat without per-service topics.",
                exc,
            )

        # ─── Topic registry + persistence ────────────────────────────────
        state_dir = Path(config.socket_path).parent
        topics_path = state_dir / f"topics-{config_hash}.json"
        topic_store = JsonFileTopicStore(topics_path)
        topic_registry = TopicRegistry()
        topic_registry.bulk_load(topic_store.load())

        resolve_topic_uc = ResolveTopicUseCase(
            _registry=topic_registry,
            _store=topic_store,
            _gateway=gateway,
            _chat_id=config.chat_id,
            _now=time.time,
        )

        telegram_io_facade = TelegramIOFacade(
            _gateway=gateway,
            _set_commands_uc=set_commands_uc,
            _forum_mode=forum_mode,
            _registry=topic_registry,
            _resolve_topic_uc=resolve_topic_uc,
        )

        # ─── Facade-dependent use cases + routers ────────────────────────
        from snitchbot.sidecar.interactive.app.use_cases.chart_query import ChartQuery
        from snitchbot.sidecar.interactive.app.use_cases.export_query import ExportQuery
        from snitchbot.sidecar.interactive.ports.driven.asciichart_renderer import (
            AsciichartRenderer,
        )

        status_query = StatusQuery(
            _registry=registry,
            _session=session,
            _queue=queue,
            _dedup_cache=dedup,
            _rate_bucket=rate_bucket,
            _mute_state=mute,
            _recent_buffer=recent_buffer,
            _stats=stats,
            _config=config,
            _lib_version=_LIB_VERSION,
            _telegram_io=telegram_io_facade,
        )

        last_query = LastQuery(
            _recent_buffer=recent_buffer,
            _config=config,
            _telegram_io=telegram_io_facade,
        )

        test_uc = TestUC(
            _registry=registry,
            _session=session,
            _queue=queue,
            _gateway=gateway,
            _config=config,
            _lib_version=_LIB_VERSION,
            _chat_id=config.chat_id,
            _latency_buffer=_latency_buffer,
            _telegram_io=telegram_io_facade,
        )

        chart_query = ChartQuery(
            _registry=registry,
            _renderer=AsciichartRenderer(),
            _chart_width=config.chart_width,
            _telegram_io=telegram_io_facade,
        )

        export_query = ExportQuery(
            _registry=registry,
            _gateway=gateway,
            _chat_id=config.chat_id,
            _telegram_io=telegram_io_facade,
        )

        command_router = CommandRouter(
            _status_query=status_query,
            _last_query=last_query,
            _test_uc=test_uc,
            _mute_uc=mute_uc,
            _unmute_uc=unmute_uc,
            _chart_query=chart_query,
            _export_query=export_query,
            _gateway=gateway,
            _chat_id=config.chat_id,
            _command_budget=cmd_budget,
        )

        long_polling = LongPollingController(
            _gateway=gateway,
            _command_router=command_router,
            _callback_router=callback_router,
            _chat_id=config.chat_id,
            _session=session,
            _stats=stats,
            _set_commands_fn=set_commands_uc,
        )

        live_message = None
        if config.live_dashboard:
            live_message_state = LiveMessageState(service=config.sidecar_service)
            sidecar_started_wall = time.time()
            live_message = LiveMessageUpdaterWorkflow(
                _gateway=gateway,
                _telegram_io=telegram_io_facade,
                _chat_id=config.chat_id,
                _service=config.sidecar_service,
                _state=live_message_state,
                _sidecar_started_at=sidecar_started_wall,
                _recent_buffer=recent_buffer,
            )

        dispatch = DispatchLoopWorkflow(
            _queue=queue,
            _rate_bucket=rate_bucket,
            _dedup_cache=dedup,
            _render_fn=_render,
            _gateway=gateway,
            _chat_id=config.chat_id,
            _telegram_io=telegram_io_facade,
        )

        poll_task = asyncio.create_task(_poll_shutdown())
        recv_task = asyncio.create_task(recv_loop.run())

        # Register bot commands immediately (don't wait for first getUpdates)
        try:
            await set_commands_uc()
            logger.debug("setMyCommands registered at startup")
        except Exception:
            logger.debug("setMyCommands failed at startup (non-fatal)", exc_info=True)

        async def _dispatch_tick() -> None:
            while not shutdown_event.is_set():
                try:
                    await dispatch.tick()
                except Exception:
                    logger.exception("dispatch tick error")
                await asyncio.sleep(0.1)

        async def _idle_tick() -> None:
            while not shutdown_event.is_set():
                if idle_uc():
                    logger.info("Idle timeout — shutting down")
                    shutdown_event.set()
                    break
                await asyncio.sleep(5.0)

        _sample_sec = config.sample_interval_sec

        async def _vitals_tick() -> None:
            """Sample vitals at configured interval per client."""
            while not shutdown_event.is_set():
                try:
                    vitals_workflow.run_sampling_tick(registry.clients_dict, now=time.monotonic(), session=session)
                except Exception:
                    logger.exception("vitals tick error")
                await asyncio.sleep(float(_sample_sec))

        async def _live_message_tick() -> None:
            """Update live dashboard every 10s."""
            while not shutdown_event.is_set():
                try:
                    await live_message.tick(
                        clients=registry.clients_dict,
                        now=time.time(),
                        app_totals={
                            "rss": session.app_total_rss_bytes,
                            "total_rss": session.app_total_rss_bytes,
                            "cpu": session.app_total_cpu_percent,
                            "total_cpu": session.app_total_cpu_percent,
                            "children": session.app_children_count,
                        },
                    )
                except Exception:
                    logger.exception("live message tick error")
                await asyncio.sleep(10.0)

        async def _edit_flusher_tick() -> None:
            while not shutdown_event.is_set():
                try:
                    items = edit_flusher.tick(now=time.monotonic())
                    for item in items:
                        queue.enqueue(item)
                except Exception:
                    logger.exception("edit flusher tick error")
                await asyncio.sleep(2.0)

        dispatch_task = asyncio.create_task(_dispatch_tick())
        idle_task = asyncio.create_task(_idle_tick())
        vitals_task = asyncio.create_task(_vitals_tick())
        live_message_task = (
            asyncio.create_task(_live_message_tick())
            if live_message is not None else None
        )
        edit_flusher_task = asyncio.create_task(_edit_flusher_tick())
        long_polling_task = asyncio.create_task(long_polling.run())

        await shutdown_event.wait()

        # LM6: graceful shutdown — final 🔴 edit on live message
        if live_message is not None:
            try:
                await live_message.shutdown_edit(now=time.time())
            except Exception:
                logger.debug("shutdown: live_message.shutdown_edit failed", exc_info=True)

        # §7.7 Step 2: Drain central queue (up to 5s)
        try:
            deadline = time.monotonic() + 5.0
            while len(queue) > 0 and time.monotonic() < deadline:
                await dispatch.tick()
                await asyncio.sleep(0.05)
        except Exception:
            logger.debug("shutdown: queue drain error", exc_info=True)

        # Graceful shutdown — stop recv loop first (closes socket, unblocks executor)
        recv_loop.stop()
        long_polling.stop()
        poll_task.cancel()
        dispatch_task.cancel()
        idle_task.cancel()
        vitals_task.cancel()
        if live_message_task is not None:
            live_message_task.cancel()
        edit_flusher_task.cancel()
        long_polling_task.cancel()

        # Wait for recv task to finish (socket timeout of 0.5s unblocks executor)
        try:
            await asyncio.wait_for(recv_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, OSError, Exception):
            recv_task.cancel()

        # Suppress cancellation on other tasks
        all_tasks = [
            poll_task, dispatch_task, idle_task, vitals_task,
            edit_flusher_task, long_polling_task,
        ]
        if live_message_task is not None:
            all_tasks.append(live_message_task)
        for t in all_tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                logger.debug("shutdown: task cleanup", exc_info=True)

        listening.close()
        listening.unlink()
        await gateway.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        pass
    finally:
        # Ensure socket cleaned up even on unexpected exit
        try:
            listening.close()
            listening.unlink()
        except Exception:
            logger.debug("shutdown: socket cleanup error", exc_info=True)

    sys.exit(0)


if __name__ == "__main__":
    main()
