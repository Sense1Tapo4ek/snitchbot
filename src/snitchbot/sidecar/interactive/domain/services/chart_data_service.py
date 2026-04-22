"""Chart data extraction and downsampling — pure domain service.

Stdlib only. Extracts time-sliced metric series from a vitals history deque
and downsamples to fit chart rendering constraints.
"""
from collections import deque

__all__ = [
    "extract_metric_series",
    "extract_time_range",
    "export_vitals_csv",
    "downsample",
]

_METRIC_EXTRACTORS = {
    "cpu": lambda s: s.cpu_percent,
    "mem": lambda s: s.rss_bytes / (1024 * 1024),  # -> MB
    "fds": lambda s: s.fds,
    "threads": lambda s: s.threads,
}

VALID_METRICS = frozenset(_METRIC_EXTRACTORS.keys())


def extract_metric_series(
    history: deque,
    *,
    metric: str,
    window_sec: float,
    now: float,
) -> list[float]:
    """Extract a time-sliced list of metric values from history.

    Args:
        history: deque of VitalsSnapshot (most recent at right end).
        metric: One of 'cpu', 'mem', 'fds', 'threads'.
        window_sec: How far back to look (in seconds).
        now: Current timestamp (same clock as VitalsSnapshot.sampled_at).

    Returns:
        List of float values in chronological order. Skips None values (V8).
    """
    extractor = _METRIC_EXTRACTORS.get(metric)
    if extractor is None:
        return []

    cutoff = now - window_sec
    values: list[float] = []
    for snap in history:
        if snap.sampled_at < cutoff:
            continue
        val = extractor(snap)
        if val is not None:
            values.append(float(val))
    return values


def extract_time_range(
    history: deque,
    *,
    window_sec: float,
    now: float,
    mono_to_wall_offset: float,
) -> tuple[float, float] | None:
    """Return (first_ts, last_ts) of snapshots within the window.

    Timestamps are wall-clock (converted from monotonic via offset).
    ``mono_to_wall_offset`` = ``time.time() - time.monotonic()``.
    Returns None if no snapshots in range.
    """
    cutoff = now - window_sec
    first_mono: float | None = None
    last_mono: float | None = None
    for snap in history:
        if snap.sampled_at < cutoff:
            continue
        if first_mono is None:
            first_mono = snap.sampled_at
        last_mono = snap.sampled_at

    if first_mono is None or last_mono is None:
        return None

    return (first_mono + mono_to_wall_offset, last_mono + mono_to_wall_offset)


def downsample(series: list[float], max_points: int = 60) -> list[float]:
    """Reduce series length by averaging consecutive groups.

    If len(series) <= max_points, returns as-is.
    Otherwise, divides into max_points groups and averages each.
    """
    n = len(series)
    if n <= max_points:
        return series

    group_size = n / max_points
    result: list[float] = []
    for i in range(max_points):
        start = int(i * group_size)
        end = int((i + 1) * group_size)
        chunk = series[start:end]
        if chunk:
            result.append(sum(chunk) / len(chunk))
    return result


def export_vitals_csv(
    history: deque,
    *,
    window_sec: float,
    now: float,
    mono_to_wall_offset: float,
) -> str:
    """Export vitals snapshots as CSV text.

    Columns: timestamp, rss_mb, cpu_percent, threads, fds.
    Timestamps are wall-clock UTC (converted from monotonic).
    ``mono_to_wall_offset`` = ``time.time() - time.monotonic()``.
    """
    from datetime import datetime, timezone

    mono_offset = mono_to_wall_offset

    lines = ["timestamp,rss_mb,cpu_percent,threads,fds"]
    cutoff = now - window_sec

    for snap in history:
        if snap.sampled_at < cutoff:
            continue
        wall_ts = snap.sampled_at + mono_offset
        ts_str = datetime.fromtimestamp(
            wall_ts, tz=timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S")
        rss_mb = snap.rss_bytes / (1024 * 1024)
        fds_str = str(snap.fds) if snap.fds is not None else ""
        lines.append(
            f"{ts_str},{rss_mb:.1f},{snap.cpu_percent:.1f},"
            f"{snap.threads},{fds_str}"
        )

    return "\n".join(lines) + "\n"
