"""File descriptor anomaly detector — v2 unified 3-mode model.

Pure domain service — stdlib only, no I/O, no frameworks.

Replaces fd_leak_service.py. Supports ceiling, spike, drop modes.
Handles V8 degradation (fds=None) gracefully.
"""
from __future__ import annotations

from collections import deque

from snitchbot.shared.domain.anomaly_config_vo import FdAnomalyConfig

from .detection_modes_service import check_ceiling, check_drop, check_spike
from .window_avg_service import compute_window_averages

__all__ = ["check_fds"]


def check_fds(
    history: deque,
    config: FdAnomalyConfig,
    sample_interval_sec: int = 5,
) -> list[dict]:
    """Check FD anomalies across all 3 modes.

    Returns a list of 0–3 anomaly result dicts (ceiling, spike, drop).
    Returns empty list if any sample has fds=None (V8 degradation).
    """
    wa = compute_window_averages(
        history,
        duration_sec=config.duration_sec,
        baseline_duration_sec=config.baseline_duration_sec,
        sample_interval_sec=sample_interval_sec,
        extract_metric=lambda s: s.fds,  # returns None for V8
    )
    if wa is None:
        return []

    results: list[dict] = []

    # 1. Ceiling (ulimit protection)
    ceiling = check_ceiling(
        current=wa.current,
        max_value=float(config.max_fds) if config.max_fds is not None else None,
    )
    if ceiling is not None:
        results.append(_build_result(
            anomaly_type="fds_ceiling",
            severity=ceiling["severity"],
            current=wa.current,
            baseline=wa.baseline_avg,
            window=config.duration,
            details={
                "mode": "ceiling",
                "current_fds": int(wa.current),
                "max_fds": config.max_fds,
            },
        ))

    # 2. Spike (FD leak)
    spike = check_spike(
        short_avg=wa.short_avg,
        baseline_avg=wa.baseline_avg,
        ratio=config.spike_ratio,
        min_delta=float(config.min_spike_delta) if config.min_spike_delta is not None else None,
    )
    if spike is not None:
        results.append(_build_result(
            anomaly_type="fds_spike",
            severity="error",  # FD leaks are always error severity
            current=wa.current,
            baseline=wa.baseline_avg,
            window=config.duration,
            details={
                "mode": "spike",
                "short_avg_fds": round(wa.short_avg, 1),
                "baseline_avg_fds": round(wa.baseline_avg, 1),
                "actual_ratio": round(spike["actual_ratio"], 2),
                "delta_fds": int(spike["actual_delta"]),
            },
        ))

    # 3. Drop (pool collapse)
    drop = check_drop(
        short_avg=wa.short_avg,
        baseline_avg=wa.baseline_avg,
        ratio=config.drop_ratio,
        min_delta=float(config.min_drop_delta) if config.min_drop_delta is not None else None,
    )
    if drop is not None:
        results.append(_build_result(
            anomaly_type="fds_drop",
            severity=drop["severity"],
            current=wa.current,
            baseline=wa.baseline_avg,
            window=config.duration,
            details={
                "mode": "drop",
                "short_avg_fds": round(wa.short_avg, 1),
                "baseline_avg_fds": round(wa.baseline_avg, 1),
                "actual_ratio": round(drop["actual_ratio"], 2),
                "drop_fds": int(drop["actual_delta"]),
            },
        ))

    return results


def _build_result(
    *,
    anomaly_type: str,
    severity: str,
    current: float,
    baseline: float,
    window: str | int,
    details: dict,
) -> dict:
    return {
        "anomaly_type": anomaly_type,
        "current": current,
        "baseline": baseline,
        "threshold_pct": 0.0,
        "window": str(window),
        "severity": severity,
        "details": details,
    }
