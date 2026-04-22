"""Sidecar driving adapter: async DGRAM recv loop.

Reads datagrams from the listening socket, decodes with msgpack, routes:
- type="hello"      -> register_client_uc
- known PID event   -> enqueue to central queue (via injected enqueue_fn)
- unknown PID       -> increment stats, drop
- decode error      -> increment stats, don't crash
"""
import asyncio
import logging
import time

from snitchbot.shared.adapters.driven.codec.msgpack_codec import CodecError
from snitchbot.shared.domain import RecentEvent
from snitchbot.sidecar.ingest.app.interfaces.i_listening_socket import IListeningSocket
from snitchbot.sidecar.ingest.app.interfaces.i_recv_loop_deps import (
    EnqueueFn,
    FingerprintFn,
    ICodec,
    IDedupCache,
    IEventQueue,
    IRecentBuffer,
    IRegisterClientUC,
    ISidecarSession,
)
from snitchbot.sidecar.ingest.domain.client_registry_agg import ClientRegistry

__all__ = ["RecvLoop"]

logger = logging.getLogger("snitchbot.sidecar.recv_loop")


class RecvLoop:
    """Async recv loop for the sidecar (driving adapter).

    Parameters
    ----------
    socket          : IListeningSocket (recvfrom / sendto / close)
    codec           : ICodec (pack / unpack)
    register_uc     : IRegisterClientUC callable
    registry        : ClientRegistry
    queue           : IEventQueue — central event queue
    stats           : dict[str, int] — sidecar counter namespace
    enqueue_fn      : EnqueueFn (optional) — classify and enqueue; injected at
                      composition time to avoid cross-context imports. Signature:
                      (event, fingerprint) -> (accepted, action, enriched).
                      When None, a default passthrough enqueue is used.
    dedup_cache     : IDedupCache (optional) — retained for backward compat /
                      testing; unused when enqueue_fn is provided.
    fingerprint_fn  : FingerprintFn (optional) — compute fingerprint
    session         : ISidecarSession (optional) — mark activity on events
    recent_buffer   : IRecentBuffer (optional) — record recent events
    """

    def __init__(
        self,
        *,
        socket: IListeningSocket,
        codec: ICodec,
        register_uc: IRegisterClientUC,
        registry: ClientRegistry,
        queue: IEventQueue,
        stats: dict[str, int],
        enqueue_fn: EnqueueFn | None = None,
        dedup_cache: IDedupCache | None = None,
        fingerprint_fn: FingerprintFn | None = None,
        session: ISidecarSession | None = None,
        recent_buffer: IRecentBuffer | None = None,
    ) -> None:
        self._socket = socket
        self._codec = codec
        self._register_uc = register_uc
        self._registry = registry
        self._queue = queue
        self._stats = stats
        self._enqueue_fn = enqueue_fn
        self._dedup_cache = dedup_cache
        self._fingerprint_fn = fingerprint_fn
        self._session = session
        self._recent_buffer = recent_buffer
        self._running = False

    async def run(self) -> None:
        """Main loop. Runs until stop() is called or an unexpected OSError."""
        self._running = True
        loop = asyncio.get_running_loop()

        while self._running:
            try:
                data, addr = await loop.run_in_executor(None, self._socket.recvfrom)
            except TimeoutError:
                # Socket read timeout — loop back to check _running flag
                continue
            except OSError:
                if not self._running:
                    break
                raise

            try:
                msg = self._codec.unpack(data)
            except CodecError:
                self._stats["decode_errors"] = self._stats.get("decode_errors", 0) + 1
                logger.debug("recv_loop: decode error, dropping datagram")
                continue

            await self._route(msg, addr)

    async def _route(self, msg: dict, addr: str) -> None:
        msg_type = msg.get("type")

        if msg_type == "hello":
            logger.debug("recv: hello from pid=%s", msg.get("pid"))
            result = self._register_uc(hello=msg, sender_addr=addr)
            reply_bytes = self._codec.pack(result)
            self._socket.sendto(reply_bytes, addr)
            logger.debug("recv: hello_ack sent to %s", addr)
            return

        # Event from a client — route by pid
        pid = msg.get("pid")
        client_state = self._registry.get_by_pid(pid) if pid is not None else None
        if pid is not None and client_state is not None:
            # Phase 4: update last_seen on every event
            client_state.last_seen = time.time()
            if self._session is not None:
                self._session.mark_activity()

            # Goodbye protocol: mark client if it sent a lifecycle shutdown
            if (
                msg.get("kind") == "lifecycle"
                and (msg.get("payload") or {}).get("phase") == "shutdown"
            ):
                client_state.shutdown_received = True

            fp = self._fingerprint_fn(msg) if self._fingerprint_fn is not None else None

            if self._enqueue_fn is not None:
                # Preferred path: injected callable handles classify + enqueue
                accepted, action, enriched = self._enqueue_fn(msg, fp)
            else:
                # Fallback: simple passthrough enqueue via IEventQueue Protocol
                action = "new_alert"
                enriched = {**msg, "fingerprint": fp, "action": action}
                accepted = self._queue.enqueue(enriched)

            if accepted:
                logger.debug(
                    "recv: enqueued kind=%s action=%s fp=%s",
                    msg.get("kind"), action, fp,
                )
                # Record in recent buffer for /status traffic counters and /last
                if self._recent_buffer is not None:
                    payload = msg.get("payload") or {}
                    self._recent_buffer.add(RecentEvent(
                        ts=msg.get("ts", 0.0),
                        fingerprint=fp,
                        severity=msg.get("severity"),
                        exception_type=payload.get("exception_type"),
                        message=payload.get("text") or payload.get("message"),
                        pid=msg.get("pid"),
                        kind=msg.get("kind", ""),
                    ))
            else:
                self._stats["queue_full_drops"] = (
                    self._stats.get("queue_full_drops", 0) + 1
                )
                logger.debug("recv: queue full, dropped event kind=%s", msg.get("kind"))
            return

        logger.debug("recv: unknown client pid=%s, dropping", pid)
        self._stats["unknown_client_messages"] = (
            self._stats.get("unknown_client_messages", 0) + 1
        )

    def stop(self) -> None:
        """Signal the loop to stop and unblock the blocking recvfrom in executor."""
        self._running = False
        # Close socket to unblock blocking recvfrom in executor
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                logger.debug("recv_loop: socket close error", exc_info=True)
