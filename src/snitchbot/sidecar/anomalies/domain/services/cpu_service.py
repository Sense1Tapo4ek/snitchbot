"""CPU anomaly detector — v2 unified 3-mode model.

Pure domain service — stdlib only, no I/O, no frameworks.

Replaces cpu_sustained_service.py. Supports ceiling, spike, drop modes.
"""
from __future__ import annotations

from collections import deque

from snitchbot.shared.domain.anomaly_config_vo import CpuAnomalyConfig

from .detection_modes_service import check_ceiling, check_drop, check_spike
from .window_avg_service import compute_window_averages

__all__ = ["check_cpu"]


def check_cpu(
    history: deque,
    config: CpuAnomalyConfig,
    sample_interval_sec: int = 5,
) -> list[dict]:
    """Check CPU anomalies across all 3 modes.

    Returns a list of 0–3 anomaly result dicts (ceiling, spike, drop).
    """
    wa = compute_window_averages(
        history,
        duration_sec=config.duration_sec,
        baseline_duration_sec=config.baseline_duration_sec,
        sample_interval_sec=sample_interval_sec,
        extract_metric=lambda s: s.cpu_percent,
    )
    if wa is None:
        return []

    results: list[dict] = []

    # 1. Ceiling
    ceiling = check_ceiling(current=wa.current, max_value=config.max_percent)
    if ceiling is not None:
        results.append(_build_result(
            anomaly_type="cpu_ceiling",
            severity=ceiling["severity"],
            current=wa.current,
            baseline=wa.baseline_avg,
            window=config.duration,
            details={
                "mode": "ceiling",
                "current_percent": round(wa.current, 1),
                "max_percent": config.max_percent,
            },
        ))

    # 2. Spike
    spike = check_spike(
        short_avg=wa.short_avg,
        baseline_avg=wa.baseline_avg,
        ratio=config.spike_ratio,
        min_delta=config.min_spike_delta,
    )
    if spike is not None:
        results.append(_build_result(
            anomaly_type="cpu_spike",
            severity=spike["severity"],
            current=wa.current,
            baseline=wa.baseline_avg,
            window=config.duration,
            details={
                "mode": "spike",
                "short_avg_percent": round(wa.short_avg, 1),
                "baseline_avg_percent": round(wa.baseline_avg, 1),
                "actual_ratio": round(spike["actual_ratio"], 2),
            },
        ))

    # 3. Drop (CPU starvation)
    drop = check_drop(
        short_avg=wa.short_avg,
        baseline_avg=wa.baseline_avg,
        ratio=config.drop_ratio,
        min_delta=config.min_drop_delta,
    )
    if drop is not None:
        results.append(_build_result(
            anomaly_type="cpu_drop",
            severity=drop["severity"],
            current=wa.current,
            baseline=wa.baseline_avg,
            window=config.duration,
            details={
                "mode": "drop",
                "short_avg_percent": round(wa.short_avg, 1),
                "baseline_avg_percent": round(wa.baseline_avg, 1),
                "actual_ratio": round(drop["actual_ratio"], 2),
                "drop_delta": round(drop["actual_delta"], 1),
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
