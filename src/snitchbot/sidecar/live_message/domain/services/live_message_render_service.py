"""Live message render service.

Pure domain: no I/O, no frameworks, stdlib only. Mirrors the /status layout
but drops the Mutes/Internal blocks, uses a fixed 5-minute counter window,
appends ``· live`` to the header, and shows vitals columns
(rss/cpu/threads/fds) instead of last-seen times.
"""
from snitchbot.shared.constants import SEPARATOR
from snitchbot.shared.domain import ClientState
from snitchbot.shared.domain.services import fmt_uptime, fmt_utc

__all__ = ["render_live_message"]

_MAX_CLIENTS = 15

_HEALTH_GREEN = "🟢"
_HEALTH_YELLOW = "🟡"
_HEALTH_RED = "🔴"


def _health_icon(clients: list[ClientState]) -> str:
    """Determine health icon based on client statuses (spec §5.2, interactive-tg §4.4)."""
    if not clients:
        return _HEALTH_RED
    statuses = {c.vitals_status for c in clients if c.vitals_status != "dead"}
    if not statuses:
        return _HEALTH_RED
    if "unavailable" in statuses:
        return _HEALTH_YELLOW
    if "stale" in statuses:
        return _HEALTH_YELLOW
    return _HEALTH_GREEN


def _rss_mb(rss_bytes: int) -> int:
    """Round bytes to whole MB for stable hash (spec §5.7)."""
    return rss_bytes // (1024 * 1024)


def _cpu_str(cpu_percent: float) -> str:
    """Format CPU to 1 decimal for stable hash (spec §5.7)."""
    return f"{cpu_percent:.1f}%"


def _render_client_row(client: ClientState) -> str:
    """Render one client row in the vitals table (spec §5.8, LM8)."""
    pid = client.pid
    role = client.role

    if client.vitals_status == "unavailable" or client.latest_vitals is None:
        return (
            f"{pid:<7}{role:<10}"
            f"{'—':<8}{'—':<8}{'—':<6}{'—':<6}{'—':<3}"
            f"{'—':<8}{'—':<4}  (unavail)"
        )

    v = client.latest_vitals
    rss = f"{_rss_mb(v.rss_bytes)} MB"
    total_rss = f"{_rss_mb(v.total_rss_bytes)} MB"
    cpu = _cpu_str(v.cpu_percent)
    total_cpu = _cpu_str(v.total_cpu_percent)
    children = str(v.children_count)
    threads = str(v.threads)
    fds = str(v.fds) if v.fds is not None else "—"

    row = (
        f"{pid:<7}{role:<10}"
        f"{rss:<8}{total_rss:<8}"
        f"{cpu:<6}{total_cpu:<6}"
        f"{children:<3}"
        f"{threads:<8}{fds:<4}"
    )
    if client.vitals_status == "stale":
        row += "  (stale)"
    return row


def render_live_message(
    *,
    service: str,
    clients: list[ClientState],
    sidecar_started_at: float,
    counters: dict[str, int],
    now: float,
    app_totals: dict[str, int | float] | None = None,
) -> str:
    """Render live dashboard HTML for Telegram (parse_mode=HTML).

    Args:
        service:            service name (used in header)
        clients:            list of all ClientState objects (dead ones are filtered)
        sidecar_started_at: wall-clock time the sidecar process started
        counters:           dict with 'errors', 'warnings', 'slow', 'anomaly' counts (5m window)
        now:                current wall-clock time
        app_totals:         optional dict with 'rss', 'cpu', 'children' keys for app total row

    Returns:
        HTML string suitable for Telegram editMessageText / sendMessage.
    """
    # Filter out dead clients — they are removed from the table (spec §5.8)
    live_clients = [c for c in clients if c.vitals_status != "dead"]

    icon = _health_icon(live_clients)
    lines: list[str] = []
    lines.append(f"{icon} <b>{service}</b> · live")
    lines.append(SEPARATOR)
    lines.append("")
    n_total = len(live_clients)
    lines.append(f"<b>Clients ({n_total})</b>")
    if n_total > 0:
        lines.append("<pre>")
        lines.append(
            f"{'PID':<7}{'role':<10}"
            f"{'rss':<8}{'total':<8}"
            f"{'cpu':<6}{'total':<6}"
            f"{'ch':<3}"
            f"{'threads':<8}{'fds':<4}"
        )
        shown = live_clients[:_MAX_CLIENTS]
        for c in shown:
            lines.append(_render_client_row(c))
        if n_total > _MAX_CLIENTS:
            lines.append(f"... {n_total - _MAX_CLIENTS} more")
        # Application total row
        if app_totals is not None:
            app_rss = f"{_rss_mb(int(app_totals.get('rss', 0)))} MB"
            app_total_rss = f"{_rss_mb(int(app_totals.get('total_rss', 0)))} MB"
            app_cpu = _cpu_str(float(app_totals.get('cpu', 0.0)))
            app_total_cpu = _cpu_str(float(app_totals.get('total_cpu', 0.0)))
            app_children = str(int(app_totals.get('children', 0)))
            lines.append(
                f"{'TOTAL':<7}{'':<10}"
                f"{app_rss:<8}{app_total_rss:<8}"
                f"{app_cpu:<6}{app_total_cpu:<6}"
                f"{app_children:<3}"
                f"{'':<8}{'':<4}"
            )
        lines.append("</pre>")
    lines.append("")
    uptime_sec = now - sidecar_started_at
    uptime_str = fmt_uptime(uptime_sec)
    updated_str = fmt_utc(now)
    lines.append("<b>Sidecar</b>")
    lines.append(f"  uptime   {uptime_str}")
    lines.append(f"  updated  {updated_str}")
    lines.append("")
    errors = counters.get("errors", 0)
    warnings = counters.get("warnings", 0)
    slow = counters.get("slow", 0)
    anomaly = counters.get("anomaly", 0)
    lines.append("<b>Last 5m</b>")
    lines.append(f"  errors    {errors}")
    lines.append(f"  warnings  {warnings}")
    lines.append(f"  slow      {slow}")
    lines.append(f"  anomaly   {anomaly}")

    return "\n".join(lines)
