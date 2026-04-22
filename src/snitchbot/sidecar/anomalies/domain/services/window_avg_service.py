"""Dual-window averaging for anomaly detection.

Pure domain service — stdlib only, no I/O, no frameworks.

Computes short-window and baseline-window averages from a history deque,
used by all 4 metric detectors for ceiling/spike/drop modes.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Callable

__all__ = ["WindowAverages", "compute_window_averages"]

_MIN_WINDOW_SAMPLES = 3


class WindowAverages:
    """Result of dual-window computation."""

    __slots__ = (
        "short_avg", "baseline_avg", "short_count", "baseline_count",
        "current",
    )

    def __init__(
        self,
        *,
        short_avg: float,
        baseline_avg: float,
        short_count: int,
        baseline_count: int,
        current: float,
    ) -> None:
        self.short_avg = short_avg
        self.baseline_avg = baseline_avg
        self.short_count = short_count
        self.baseline_count = baseline_count
        self.current = current


def compute_window_averages(
    history: deque,
    *,
    duration_sec: int,
    baseline_duration_sec: int,
    sample_interval_sec: int,
    extract_metric: Callable,
) -> WindowAverages | None:
    """Compute short-window and baseline-window averages from history.

    Args:
        history: deque of VitalsSnapshot, most recent at the right end.
        duration_sec: Short window duration in seconds.
        baseline_duration_sec: Baseline window duration in seconds.
        sample_interval_sec: Interval between samples (e.g. 5 for vitals).
        extract_metric: Callable(snapshot) -> float | int | None.
            Returns None for missing metrics (e.g. fds=None on V8 degradation).

    Returns:
        WindowAverages or None if insufficient data or any metric is None.
    """
    n = len(history)
    if n < _MIN_WINDOW_SAMPLES:
        return None

    snaps = list(history)

    # Compute sample counts from durations
    short_count = max(_MIN_WINDOW_SAMPLES, duration_sec // sample_interval_sec)
    baseline_count = max(_MIN_WINDOW_SAMPLES, baseline_duration_sec // sample_interval_sec)

    # Clamp to available history
    short_count = min(short_count, n)
    baseline_count = min(baseline_count, n)

    # Extract short window (rightmost samples)
    short_values: list[float] = []
    for snap in snaps[-short_count:]:
        val = extract_metric(snap)
        if val is None:
            return None  # V8 degradation — can't compute
        short_values.append(float(val))

    # Extract baseline window
    baseline_values: list[float] = []
    for snap in snaps[-baseline_count:]:
        val = extract_metric(snap)
        if val is None:
            return None
        baseline_values.append(float(val))

    if len(short_values) < _MIN_WINDOW_SAMPLES or len(baseline_values) < _MIN_WINDOW_SAMPLES:
        return None

    short_avg = sum(short_values) / len(short_values)
    baseline_avg = sum(baseline_values) / len(baseline_values)
    current = short_values[-1]  # most recent value

    return WindowAverages(
        short_avg=short_avg,
        baseline_avg=baseline_avg,
        short_count=len(short_values),
        baseline_count=len(baseline_values),
        current=current,
    )
