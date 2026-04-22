"""TestUC — /test command handler.

Always replies: bypasses dedup and the main rate-limit bucket, and queues
at TEST_RESPONSE priority so the reply jumps the queue.
"""
import time
from dataclasses import dataclass, field

from snitchbot.shared.constants import SEPARATOR
from snitchbot.shared.domain.services import fmt_uptime
from snitchbot.shared.domain.services import fmt_utc as _fmt_utc
from snitchbot.sidecar.interactive.app.interfaces import (
    IClientRegistry,
    ISidecarConfig,
    ISidecarSession,
    ITelegramIOFacade,
)
from snitchbot.sidecar.interactive.app.use_cases._service_scope import (
    resolve_service_scope,
)

__all__ = ["TestUC"]


@dataclass(frozen=True, slots=True, kw_only=True)
class TestUC:
    """Use case for /test command.

    Dependencies:
        _registry       : ClientRegistry
        _session        : SidecarSession
        _queue          : CentralQueue
        _command_budget : CommandBudget  (bypass — not consumed)
        _gateway        : ITelegramGateway
        _config         : SidecarConfig
        _lib_version    : str
        _chat_id        : str
        _latency_buffer : list[float]  (last 10 sendMessage latencies, mutable)
    """

    _registry: IClientRegistry
    _session: ISidecarSession
    _queue: object  # IEventQueue — not inspected here, kept opaque
    _gateway: object  # ITelegramGateway — not called here, kept opaque
    _config: ISidecarConfig
    _lib_version: str
    _chat_id: str
    _latency_buffer: list[float]  # last 10 sendMessage latencies
    _telegram_io: ITelegramIOFacade | None = field(default=None)

    async def __call__(
        self,
        *,
        message_id: int | None = None,
        now: float | None = None,
        message_thread_id: int | None = None,
    ) -> dict:
        """Execute /test: build reply and send it head-of-queue.

        Args:
            message_id: TG message_id of the /test message (for reply_to).
            now:        override current time (for tests).
            message_thread_id: forum topic id the command arrived on (None
                outside forum mode). F7: resolved to a service name shown in
                the reply header.

        Returns:
            {"text": ..., "parse_mode": "HTML", "reply_to_message_id": message_id}
        """
        if now is None:
            now = time.time()

        import os as _os

        # F7: resolve service scope from forum topic
        scope_service = resolve_service_scope(self._telegram_io, message_thread_id)

        pids = self._registry.all_pids()
        n_clients = len(pids)
        clients_str = f"{n_clients} active" if n_clients > 0 else "0 (waiting)"

        uptime = time.monotonic() - self._session.started_at
        uptime_str = fmt_uptime(uptime)

        lib = self._lib_version
        pid = _os.getpid()

        # Latency avg — gateway stores ms already
        buf = list(self._latency_buffer) if self._latency_buffer else []
        if buf:
            avg_ms = sum(buf[-10:]) / len(buf[-10:])
            latency_str = f"~{avg_ms:.0f} ms (avg, last {min(len(buf), 10)})"
        else:
            latency_str = "n/a"

        time_str = _fmt_utc(now)
        service = scope_service or (
            self._config.sidecar_service or self._config.service
        )

        # Health cue: simple check
        is_degraded = self._session.dispatch_degraded
        cue = "⚠ Test DEGRADED" if is_degraded else "✅ <b>Test OK</b>"

        lines = [
            cue,
            SEPARATOR,
            f"service    {service}",
            f"sidecar    uptime {uptime_str}, pid {pid}, lib {lib}",
            f"clients    {clients_str}",
            f"tg latency {latency_str}",
            f"time       {time_str}",
        ]
        text = "\n".join(lines)

        reply = {
            "text": text,
            "parse_mode": "HTML",
        }
        if message_id is not None:
            reply["reply_to_message_id"] = message_id

        return reply
