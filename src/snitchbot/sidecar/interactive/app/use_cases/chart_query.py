"""ChartQuery — /chart command use case.

Renders ASCII metric charts from client vitals history.

Usage: /chart [metric] [window]
  metric: cpu | mem | fds | threads | all (default: all)
  window: 1m | 5m | 15m | 1h | 6h | 1d (default: 5m)
"""
import time as _time
from dataclasses import dataclass, field

from snitchbot.shared.constants import SEPARATOR
from snitchbot.shared.domain.services import fmt_utc
from snitchbot.shared.domain.services import (
    WindowParseError,
    parse_window_seconds,
)
from snitchbot.sidecar.interactive.app.interfaces import ITelegramIOFacade
from snitchbot.sidecar.interactive.app.use_cases._service_scope import (
    resolve_service_scope,
)
from snitchbot.sidecar.interactive.domain.services.chart_data_service import (
    VALID_METRICS,
    downsample,
    extract_metric_series,
    extract_time_range,
)

__all__ = ["ChartQuery"]

_DEFAULT_WINDOW = "5m"
_DEFAULT_METRIC = "all"
_DEFAULT_CHART_WIDTH = 35
# Y-axis labels take ~10 chars; remaining chars = data points.
_Y_AXIS_OVERHEAD = 10


@dataclass(frozen=True, slots=True, kw_only=True)
class ChartQuery:
    """Renders ASCII charts of vitals metrics.

    Dependencies are duck-typed (Protocols) — any object with the right
    surface works. This avoids cross-context imports.
    """

    _registry: object  # IClientRegistry — .all_pids(), .get_by_pid()
    _renderer: object  # AsciichartRenderer — .render(), .render_multi()
    _chart_width: int = _DEFAULT_CHART_WIDTH
    _telegram_io: ITelegramIOFacade | None = field(default=None)

    async def __call__(
        self,
        *,
        args: str = "",
        now: float | None = None,
        message_thread_id: int | None = None,
    ) -> dict:
        """Handle /chart command. Returns reply dict for Telegram.

        ``message_thread_id`` is the forum topic id the command arrived on
        (None outside forum mode). F7: resolved to a service name; the chart
        is rendered from the first live client whose ``service`` matches.
        """
        if now is None:
            now = _time.monotonic()  # sampled_at uses monotonic clock

        # F7: resolve service scope from forum topic
        scope_service = resolve_service_scope(self._telegram_io, message_thread_id)

        metric, window_sec, window_label, error = _parse_args(args)
        if error:
            return {"text": error, "parse_mode": "HTML"}

        # Find first live client with vitals history (service-scoped if set)
        client = self._find_live_client(service=scope_service)
        if client is None:
            return {"text": "No live clients with vitals data.", "parse_mode": "HTML"}

        history = client.vitals_history

        max_pts = max(10, self._chart_width - _Y_AXIS_OVERHEAD)

        if metric == "all":
            metrics_data = {}
            for m in ("cpu", "mem", "fds", "threads"):
                series = extract_metric_series(history, metric=m, window_sec=window_sec, now=now)
                metrics_data[m] = downsample(series, max_pts)
            chart_text = self._renderer.render_multi(
                metrics_data, height=5, window_label=window_label,
            )
        else:
            series = extract_metric_series(history, metric=metric, window_sec=window_sec, now=now)
            series = downsample(series, max_pts)
            chart_text = self._renderer.render(
                series, height=10, metric=metric, window_label=window_label,
            )

        # Add time range footer
        mono_offset = _time.time() - now
        time_range = extract_time_range(
            history, window_sec=window_sec, now=now,
            mono_to_wall_offset=mono_offset,
        )
        if time_range is not None:
            first_ts, last_ts = time_range
            time_footer = f"\n{fmt_utc(first_ts)} -> {fmt_utc(last_ts)}"
            chart_text += time_footer

        service_label = scope_service or getattr(client, "service", None) or "unknown"
        header = (
            f"📊 <b>chart</b> · {_escape_html(service_label)} · "
            f"{_escape_html(metric)} · {_escape_html(window_label)}"
        )
        body = f"<pre>{_escape_html(chart_text)}</pre>"
        html = f"{header}\n{SEPARATOR}\n{body}"

        # Truncate to Telegram limit
        if len(html) > 4096:
            html = html[:4090] + "</pre>"

        return {"text": html, "parse_mode": "HTML"}

    def _find_live_client(self, *, service: str | None = None) -> object | None:
        """Return the first client with vitals_status == 'ok'.

        F7: when ``service`` is not None, only clients whose ``service``
        attribute matches are returned.
        """
        for pid in self._registry.all_pids():
            client = self._registry.get_by_pid(pid)
            if client is None or getattr(client, "vitals_status", "") != "ok":
                continue
            if service is not None and getattr(client, "service", None) != service:
                continue
            return client
        return None


def _parse_args(args: str) -> tuple[str, float, str, str | None]:
    """Parse /chart args. Returns (metric, window_sec, window_label, error_or_none)."""
    tokens = args.strip().split()

    metric = _DEFAULT_METRIC
    window_str = _DEFAULT_WINDOW

    for token in tokens:
        token_lower = token.lower()
        if token_lower in VALID_METRICS or token_lower == "all":
            metric = token_lower
        else:
            window_str = token_lower

    try:
        window_sec = parse_window_seconds(window_str)
    except WindowParseError:
        return "", 0, "", f"Invalid window: {window_str}. Use 1m, 5m, 15m, 1h, 6h, 1d."

    return metric, window_sec, window_str, None


def _escape_html(text: str) -> str:
    """Escape HTML special chars for <pre> block."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
