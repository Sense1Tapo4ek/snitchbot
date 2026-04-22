"""Thread count anomaly detector — v2 unified 3-mode model.

Pure domain service — stdlib only, no I/O, no frameworks.

Replaces thread_growth_service.py. Supports ceiling, spike, drop modes.
"""
from __future__ import annotations

from collections import deque

from snitchbot.shared.domain.anomaly_config_vo import ThreadAnomalyConfig

from .detection_modes_service import check_ceiling, check_drop, check_spike
from .window_avg_service import compute_window_averages

__all__ = ["check_threads"]


def check_threads(
    history: deque,
    config: ThreadAnomalyConfig,
    sample_interval_sec: int = 5,
) -> list[dict]:
    """Check thread anomalies across all 3 modes.

    Returns a list of 0–3 anomaly result dicts (ceiling, spike, drop).
    """
    wa = compute_window_averages(
        history,
        duration_sec=config.duration_sec,
        baseline_duration_sec=config.baseline_duration_sec,
        sample_interval_sec=sample_interval_sec,
        extract_metric=lambda s: s.threads,
    )
    if wa is None:
        return []

    results: list[dict] = []

    # 1. Ceiling
    ceiling = check_ceiling(
        current=wa.current,
        max_value=float(config.max_threads) if config.max_threads is not None else None,
    )
    if ceiling is not None:
        results.append(_build_result(
            anomaly_type="threads_ceiling",
            severity=ceiling["severity"],
            current=wa.current,
            baseline=wa.baseline_avg,
            window=config.duration,
            details={
                "mode": "ceiling",
                "current_threads": int(wa.current),
                "max_threads": config.max_threads,
            },
        ))

    # 2. Spike (thread leak)
    spike = check_spike(
        short_avg=wa.short_avg,
        baseline_avg=wa.baseline_avg,
        ratio=config.spike_ratio,
        min_delta=float(config.min_spike_delta) if config.min_spike_delta is not None else None,
    )
    if spike is not None:
        results.append(_build_result(
            anomaly_type="threads_spike",
            severity=spike["severity"],
            current=wa.current,
            baseline=wa.baseline_avg,
            window=config.duration,
            details={
                "mode": "spike",
                "short_avg_threads": round(wa.short_avg, 1),
                "baseline_avg_threads": round(wa.baseline_avg, 1),
                "actual_ratio": round(spike["actual_ratio"], 2),
                "delta_threads": int(spike["actual_delta"]),
            },
        ))

    # 3. Drop (worker collapse)
    drop = check_drop(
        short_avg=wa.short_avg,
        baseline_avg=wa.baseline_avg,
        ratio=config.drop_ratio,
        min_delta=float(config.min_drop_delta) if config.min_drop_delta is not None else None,
    )
    if drop is not None:
        results.append(_build_result(
            anomaly_type="threads_drop",
            severity=drop["severity"],
            current=wa.current,
            baseline=wa.baseline_avg,
            window=config.duration,
            details={
                "mode": "drop",
                "short_avg_threads": round(wa.short_avg, 1),
                "baseline_avg_threads": round(wa.baseline_avg, 1),
                "actual_ratio": round(drop["actual_ratio"], 2),
                "drop_threads": int(drop["actual_delta"]),
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
