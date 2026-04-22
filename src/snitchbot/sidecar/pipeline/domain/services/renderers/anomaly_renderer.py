"""Anomaly event renderer — v2 unified 3-mode model.

Handles 12 anomaly types (4 metrics × 3 modes: ceiling, spike, drop)
plus v1 deprecated types for backward compatibility.
"""
from ..html_escape_service import escape_html
from ..severity_icon_service import severity_icon
from ._common import _render_details, _render_header

__all__ = ["render_anomaly"]

_MB = 1024 * 1024


def render_anomaly(event: dict, dedup_entry: dict, service: str) -> str:
    payload = event["payload"]
    count = dedup_entry["count"]
    fingerprint = event.get("fingerprint", "")
    icon = severity_icon(dedup_entry["severity"])

    header = _render_header(
        icon=icon,
        kind_label="anomaly",
        service=service,
        fingerprint=fingerprint,
        count=count,
    )

    anomaly_type = payload.get("anomaly_type", "")
    current = payload.get("current", 0)
    baseline = payload.get("baseline", 0)
    window = escape_html(payload.get("window", ""))
    details_data = payload.get("details", {})

    title, baseline_str, current_str = _render_title(
        anomaly_type, current, baseline, window, details_data,
    )

    extra_lines = [
        f"  type      {escape_html(anomaly_type)}",
        f"  window    {window}",
        f"  baseline  {baseline_str}",
        f"  current   {current_str}",
    ]
    details = _render_details(
        ts=event.get("ts", 0.0),
        pid=event.get("pid", 0),
        count=count,
        first_seen=dedup_entry["first_seen"],
        last_seen=dedup_entry["last_seen"],
        extra_lines=extra_lines,
    )

    return "\n".join([header, title, details])


def _render_title(
    anomaly_type: str,
    current: float,
    baseline: float,
    window: str,
    details: dict,
) -> tuple[str, str, str]:
    """Return (title_html, baseline_str, current_str) for the anomaly type."""
    renderer = _TITLE_RENDERERS.get(anomaly_type)
    if renderer is not None:
        return renderer(current, baseline, window, details)
    return _render_fallback(anomaly_type, current, baseline)

def _render_memory_ceiling(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    current_mb = details.get("current_mb", current / _MB)
    max_mb = details.get("max_mb", 0)
    title = f"RSS ceiling: <b>{current_mb:.0f} MB</b> (limit {max_mb:.0f} MB)"
    return title, f"{baseline / _MB:.0f} MB", f"{current_mb:.0f} MB"


def _render_memory_spike(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    current_mb = details.get("current_mb", current / _MB)
    baseline_mb = details.get("baseline_mb", baseline / _MB)
    pct = details.get("pct_increase", 0)
    title = (
        f"RSS spike: <b>{current_mb:.0f} MB</b> "
        f"(baseline {baseline_mb:.0f} MB, +{pct}%)"
    )
    return title, f"{baseline_mb:.0f} MB", f"{current_mb:.0f} MB"


def _render_memory_drop(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    current_mb = details.get("current_mb", current / _MB)
    baseline_mb = details.get("baseline_mb", baseline / _MB)
    drop_mb = details.get("drop_mb", 0)
    title = (
        f"RSS drop: <b>{current_mb:.0f} MB</b> "
        f"(baseline {baseline_mb:.0f} MB, -{drop_mb:.0f} MB)"
    )
    return title, f"{baseline_mb:.0f} MB", f"{current_mb:.0f} MB"

def _render_cpu_ceiling(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    max_pct = details.get("max_percent", 0)
    title = f"CPU ceiling: <b>{current:.0f}%</b> (limit {max_pct:.0f}%)"
    return title, f"{baseline:.0f}%", f"{current:.0f}%"


def _render_cpu_spike(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    short_avg = details.get("short_avg_percent", current)
    baseline_avg = details.get("baseline_avg_percent", baseline)
    ratio = details.get("actual_ratio", 0)
    title = (
        f"CPU spike: <b>{short_avg:.0f}%</b> "
        f"(baseline {baseline_avg:.0f}%, ×{ratio:.1f})"
    )
    return title, f"{baseline_avg:.0f}%", f"{short_avg:.0f}%"


def _render_cpu_drop(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    short_avg = details.get("short_avg_percent", current)
    baseline_avg = details.get("baseline_avg_percent", baseline)
    drop_delta = details.get("drop_delta", 0)
    title = (
        f"CPU starvation: <b>{short_avg:.0f}%</b> "
        f"(baseline {baseline_avg:.0f}%, -{drop_delta:.0f}%)"
    )
    return title, f"{baseline_avg:.0f}%", f"{short_avg:.0f}%"

def _render_fds_ceiling(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    max_fds = details.get("max_fds", 0)
    title = f"FD ceiling: <b>{current:.0f}</b> (limit {max_fds})"
    return title, f"{baseline:.0f}", f"{current:.0f}"


def _render_fds_spike(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    delta = details.get("delta_fds", 0)
    title = f"FD leak: {baseline:.0f} -> <b>{current:.0f}</b> (+{delta})"
    return title, f"{baseline:.0f}", f"{current:.0f}"


def _render_fds_drop(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    drop = details.get("drop_fds", 0)
    title = f"FD pool collapse: {baseline:.0f} -> <b>{current:.0f}</b> (-{drop})"
    return title, f"{baseline:.0f}", f"{current:.0f}"

def _render_threads_ceiling(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    max_threads = details.get("max_threads", 0)
    title = f"Thread ceiling: <b>{current:.0f}</b> (limit {max_threads})"
    return title, f"{baseline:.0f}", f"{current:.0f}"


def _render_threads_spike(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    delta = details.get("delta_threads", 0)
    title = f"Thread growth: {baseline:.0f} -> <b>{current:.0f}</b> (+{delta})"
    return title, f"{baseline:.0f}", f"{current:.0f}"


def _render_threads_drop(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    drop = details.get("drop_threads", 0)
    title = f"Worker collapse: {baseline:.0f} -> <b>{current:.0f}</b> (-{drop})"
    return title, f"{baseline:.0f}", f"{current:.0f}"

def _render_rss_spike_v1(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    return _render_memory_spike(current, baseline, window, details)


def _render_cpu_sustained_v1(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    title = f"CPU sustained at <b>{current:.0f}%</b> for {window}"
    return title, f"{baseline:.0f}%", f"{current:.0f}%"


def _render_fd_leak_v1(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    return _render_fds_spike(current, baseline, window, details)


def _render_thread_growth_v1(
    current: float, baseline: float, window: str, details: dict,
) -> tuple[str, str, str]:
    return _render_threads_spike(current, baseline, window, details)

def _render_fallback(
    anomaly_type: str, current: float, baseline: float,
) -> tuple[str, str, str]:
    title = f"Anomaly detected: {escape_html(anomaly_type)}"
    return title, f"{baseline:.0f}", f"{current:.0f}"

_TITLE_RENDERERS = {
    # v2: 4 metrics × 3 modes
    "rss_ceiling": _render_memory_ceiling,
    "rss_spike": _render_memory_spike,
    "rss_drop": _render_memory_drop,
    "cpu_ceiling": _render_cpu_ceiling,
    "cpu_spike": _render_cpu_spike,
    "cpu_drop": _render_cpu_drop,
    "fds_ceiling": _render_fds_ceiling,
    "fds_spike": _render_fds_spike,
    "fds_drop": _render_fds_drop,
    "threads_ceiling": _render_threads_ceiling,
    "threads_spike": _render_threads_spike,
    "threads_drop": _render_threads_drop,
    # v1 deprecated (rss_spike already covered by v2 above)
    "cpu_sustained": _render_cpu_sustained_v1,
    "fd_leak": _render_fd_leak_v1,
    "thread_growth": _render_thread_growth_v1,
}
