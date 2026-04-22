"""StatusQuery — /status command handler."""
import time
from dataclasses import dataclass, field

from snitchbot.shared.constants import SEPARATOR
from snitchbot.shared.domain.services import fmt_uptime, fmt_window_label
from snitchbot.shared.domain.services import fmt_utc as _fmt_utc
from snitchbot.shared.domain.services import (
    WindowParseError,
    parse_window_seconds,
)
from snitchbot.sidecar.interactive.app.interfaces import (
    IClientRegistry,
    IDedupCache,
    IEventQueue,
    IMuteState,
    IRateBucket,
    IRecentBuffer,
    ISidecarConfig,
    ISidecarSession,
    ITelegramIOFacade,
)
from snitchbot.sidecar.interactive.app.use_cases._service_scope import (
    resolve_service_scope,
)

__all__ = ["StatusQuery"]

_DEFAULT_WINDOW_SEC = 3600.0  # 1h

_HEALTH_GREEN = "🟢"
_HEALTH_YELLOW = "🟡"
_HEALTH_RED = "🔴"


def _fmt_seen(delta: float) -> str:
    if delta < 1.0:
        return "now"
    if delta < 60:
        return f"{int(delta)}s"
    return f"{int(delta) // 60}m"


def _fmt_rss(rss_bytes: int) -> str:
    return f"{rss_bytes // (1024 * 1024)} MB"


def _fmt_cpu(pct: float) -> str:
    return f"{pct:.0f}%"


@dataclass(frozen=True, slots=True, kw_only=True)
class StatusQuery:
    """Query use case for /status command.

    Dependencies:
        _registry       : ClientRegistry
        _session        : SidecarSession
        _queue          : CentralQueue
        _dedup_cache    : DedupCache
        _rate_bucket    : RateBucket
        _mute_state     : MuteState
        _recent_buffer  : RecentEventsBuffer
        _stats          : dict (sidecar stats)
        _config         : SidecarConfig
        _lib_version    : str
    """

    _registry: IClientRegistry
    _session: ISidecarSession
    _queue: IEventQueue
    _dedup_cache: IDedupCache
    _rate_bucket: IRateBucket
    _mute_state: IMuteState
    _recent_buffer: IRecentBuffer
    _stats: dict[str, int]
    _config: ISidecarConfig
    _lib_version: str
    _telegram_io: ITelegramIOFacade | None = field(default=None)

    async def __call__(
        self,
        *,
        args: str = "",
        now: float | None = None,
        message_thread_id: int | None = None,
    ) -> dict:
        """Execute /status query.

        Args:
            args: raw argument string (e.g. "5m", "1h")
            now:  override current time (for tests)
            message_thread_id: forum topic id the command arrived on (None
                outside forum mode). F7: resolved to a service name to scope
                the rendered header.

        Returns:
            {"text": <HTML str>, "parse_mode": "HTML"}
        """
        if now is None:
            now = time.time()

        # F7: resolve service scope from forum topic
        scope_service = resolve_service_scope(self._telegram_io, message_thread_id)

        # Parse window argument
        window_sec = _DEFAULT_WINDOW_SEC
        if args.strip():
            try:
                window_sec = parse_window_seconds(args.strip())
            except WindowParseError:
                return {
                    "text": "❌ usage: /status [5m|1h|24h|7d|...]",
                    "parse_mode": "HTML",
                }

        # Build response text
        text = self._render(
            window_sec=window_sec, now=now, scope_service=scope_service,
        )
        return {"text": text, "parse_mode": "HTML"}

    def _render(
        self,
        *,
        window_sec: float,
        now: float,
        scope_service: str | None = None,
    ) -> str:
        import os as _os
        # F7: topic-scoped header overrides the global sidecar/config service
        service = scope_service or (
            self._config.sidecar_service or self._config.service
        )
        uptime = time.monotonic() - self._session.started_at
        pid = _os.getpid()

        # Determine health cue
        health = self._health_cue(now=now)

        lines: list[str] = []
        lines.append(f"{health} <b>{service}</b>")
        lines.append(SEPARATOR)

        # Sidecar block
        lines.append("<b>Sidecar</b>")
        started_wall = time.time() - uptime  # convert monotonic uptime to wall-clock start
        lines.append(f"  started    {_fmt_utc(started_wall)}")
        lines.append(f"  uptime     {fmt_uptime(uptime)}")
        lines.append(f"  lib        {self._lib_version}")
        lines.append(f"  pid        {pid}")
        lines.append("")

        # Clients block — exclude dead clients from count and table
        pids = self._registry.all_pids()
        live_clients = []
        for p in pids:
            c = self._registry.get_by_pid(p)
            if c is None or c.vitals_status != "dead":
                live_clients.append((p, c))
        n_clients = len(live_clients)
        lines.append(f"<b>Clients ({n_clients})</b>")
        if n_clients > 0:
            lines.append("<pre>")
            lines.append(f"{'PID':<7}{'role':<10}{'rss':<10}{'cpu':<8}{'seen'}")
            for p, client in live_clients[:15]:
                role = client.role if client else "unknown"
                vitals = client.latest_vitals if client else None
                vitals_status = client.vitals_status if client else "ok"
                last_seen = client.last_seen if client else 0
                if vitals_status == "unavailable":
                    rss_str = "—"
                    cpu_str = "—"
                    suffix = " (unavail)"
                elif vitals is not None:
                    rss_str = _fmt_rss(vitals.rss_bytes)
                    cpu_str = _fmt_cpu(vitals.cpu_percent)
                    suffix = " (stale)" if vitals_status == "stale" else ""
                else:
                    rss_str = "—"
                    cpu_str = "—"
                    suffix = ""
                seen_str = _fmt_seen(time.time() - last_seen) if last_seen > 0 else "?"
                lines.append(f"{p:<7}{role:<10}{rss_str:<10}{cpu_str:<8}{seen_str}{suffix}")
            if n_clients > 15:
                lines.append(f"... {n_clients - 15} more")
            lines.append("</pre>")
        lines.append("")

        # Traffic counters
        window_label = fmt_window_label(window_sec)
        counters = self._recent_buffer.traffic_counters(window_sec=window_sec, now=now)
        lines.append(f"<b>Traffic (last {window_label})</b>")
        lines.append(f"  errors          {counters.get('errors', 0)}")
        lines.append(f"  warnings        {counters.get('warnings', 0)}")
        lines.append(f"  slow calls      {counters.get('slow_calls', 0)}")
        lines.append(f"  watchdog hits   {counters.get('watchdog_hits', 0)}")
        lines.append("")

        # Internal block
        queue_depth = len(self._queue)
        queue_max = self._queue.max_size
        dedup_count = len(self._dedup_cache)
        rate_tokens = self._rate_bucket.tokens
        rate_max = self._rate_bucket.max_tokens
        dropped = self._stats.get("dropped", 0)
        lines.append("<b>Internal</b>")
        lines.append(f"  queue depth     {queue_depth} / {queue_max}")
        lines.append(f"  dedup cache     {dedup_count} / 10000")
        lines.append(f"  rate budget    {rate_tokens} / {rate_max}")
        lines.append(f"  dropped         {dropped}")

        # Mutes block
        active_mutes = self._mute_state.get_active_mutes(now)
        if active_mutes:
            lines.append("")
            lines.append(f"<b>Mutes ({len(active_mutes)})</b>")
            lines.append("<pre>")
            lines.append(f"{'fp':<9}{'what':<27}{'expires'}")
            for entry in active_mutes:
                fp = entry.fingerprint if entry.fingerprint else "global"
                exc = getattr(entry, "exception_type", None)
                what = exc or ("all events" if fp == "global" else fp)
                remaining = entry.expires_at - now
                exp_str = f"in {int(remaining // 60)}m" if remaining > 0 else "expired"
                lines.append(f"{fp:<9}{what:<27}{exp_str}")
            lines.append("</pre>")
            lines.append("<i>⚠ critical events are never muted</i>")

        return "\n".join(lines)

    def _health_cue(self, *, now: float) -> str:
        dropped = self._stats.get("dropped", 0)
        queue_depth = len(self._queue)
        queue_max = self._queue.max_size

        # Red: all clients dead, or dispatch loop backoff
        pids = self._registry.all_pids()
        if not pids:
            if not self._session.first_hello_received:
                pass  # waiting for first client — not critical yet
            else:
                return _HEALTH_RED

        # Yellow: any degradation
        if dropped > 0:
            return _HEALTH_YELLOW
        if queue_max > 0 and queue_depth >= queue_max * 0.5:
            return _HEALTH_YELLOW

        return _HEALTH_GREEN

