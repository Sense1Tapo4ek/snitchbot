"""Detection mode services — ceiling, spike, drop.

Pure domain service — stdlib only, no I/O, no frameworks.

Each function checks one detection mode and returns a result dict or None.
Used by all 4 metric detectors.
"""
from __future__ import annotations

__all__ = ["check_ceiling", "check_spike", "check_drop"]


def check_ceiling(
    *,
    current: float,
    max_value: float | None,
) -> dict | None:
    """Check ceiling mode — hard absolute threshold.

    Triggers when ``current > max_value``. Severity: ``error``.

    Returns:
        Result dict fragment or None if not triggered / disabled.
    """
    if max_value is None:
        return None
    if current <= max_value:
        return None
    return {
        "mode": "ceiling",
        "severity": "error",
        "max_value": max_value,
    }


def check_spike(
    *,
    short_avg: float,
    baseline_avg: float,
    ratio: float | None,
    min_delta: float | None,
) -> dict | None:
    """Check spike mode — relative growth of short window vs baseline.

    Triggers when BOTH:
    - ``short_avg > baseline_avg * ratio``
    - ``short_avg > baseline_avg + min_delta``

    If either ``ratio`` or ``min_delta`` is None, that condition is skipped.
    If both are None, spike mode is disabled.

    Severity: ``warning``.

    Returns:
        Result dict fragment or None if not triggered / disabled.
    """
    if ratio is None and min_delta is None:
        return None

    if baseline_avg <= 0:
        return None

    ratio_ok = ratio is None or short_avg > baseline_avg * ratio
    delta_ok = min_delta is None or short_avg > baseline_avg + min_delta

    if not (ratio_ok and delta_ok):
        return None

    actual_ratio = short_avg / baseline_avg
    actual_delta = short_avg - baseline_avg

    return {
        "mode": "spike",
        "severity": "warning",
        "actual_ratio": actual_ratio,
        "actual_delta": actual_delta,
    }


def check_drop(
    *,
    short_avg: float,
    baseline_avg: float,
    ratio: float | None,
    min_delta: float | None,
) -> dict | None:
    """Check drop mode — relative decline of short window vs baseline.

    Triggers when BOTH:
    - ``short_avg < baseline_avg * ratio``
    - ``baseline_avg - short_avg > min_delta``

    If either ``ratio`` or ``min_delta`` is None, that condition is skipped.
    If both are None, drop mode is disabled.

    Severity: ``warning``.

    Returns:
        Result dict fragment or None if not triggered / disabled.
    """
    if ratio is None and min_delta is None:
        return None

    if baseline_avg <= 0:
        return None

    ratio_ok = ratio is None or short_avg < baseline_avg * ratio
    delta_ok = min_delta is None or (baseline_avg - short_avg) > min_delta

    if not (ratio_ok and delta_ok):
        return None

    actual_ratio = short_avg / baseline_avg
    actual_delta = baseline_avg - short_avg

    return {
        "mode": "drop",
        "severity": "warning",
        "actual_ratio": actual_ratio,
        "actual_delta": actual_delta,
    }
