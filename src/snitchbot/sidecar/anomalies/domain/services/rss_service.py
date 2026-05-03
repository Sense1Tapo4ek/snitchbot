"""RSS anomaly detector — v2 unified 3-mode model.

Pure domain service — stdlib only, no I/O, no frameworks.

Supports ceiling, spike, drop modes for RSS memory.
"""
from __future__ import annotations

from collections import deque

from snitchbot.shared.domain.anomaly_config_vo import RssAnomalyConfig

from .detection_modes_service import check_ceiling, check_drop, check_spike
from .window_avg_service import compute_window_averages

__all__ = ["check_rss", "check_total_rss"]

_MB = 1024 * 1024


def _check_rss_impl(
    history: deque,
    config: RssAnomalyConfig,
    sample_interval_sec: int,
    extract_metric,
    prefix: str,
) -> list[dict]:
    """Shared implementation for rss and total_rss anomaly detection."""
    wa = compute_window_averages(
        history,
        duration_sec=config.duration_sec,
        baseline_duration_sec=config.baseline_duration_sec,
        sample_interval_sec=sample_interval_sec,
        extract_metric=extract_metric,
    )
    if wa is None:
        return []

    results: list[dict] = []
    current_mb = wa.current / _MB
    baseline_mb = wa.baseline_avg / _MB
    short_mb = wa.short_avg / _MB

    # 1. Ceiling
    ceiling = check_ceiling(current=current_mb, max_value=config.max_mb)
    if ceiling is not None:
        results.append(_build_result(
            anomaly_type=f"{prefix}_ceiling",
            severity=ceiling["severity"],
            current=wa.current,
            baseline=wa.baseline_avg,
            window=config.duration,
            details={
                "mode": "ceiling",
                "current_mb": round(current_mb, 1),
                "max_mb": config.max_mb,
            },
        ))

    # 2. Spike
    spike_min_delta = config.min_spike_mb * _MB if config.min_spike_mb is not None else None
    spike = check_spike(
        short_avg=wa.short_avg,
        baseline_avg=wa.baseline_avg,
        ratio=config.spike_ratio,
        min_delta=spike_min_delta,
    )
    if spike is not None:
        pct = int((short_mb / baseline_mb - 1) * 100) if baseline_mb > 0 else 0
        results.append(_build_result(
            anomaly_type=f"{prefix}_spike",
            severity=spike["severity"],
            current=wa.current,
            baseline=wa.baseline_avg,
            window=config.duration,
            details={
                "mode": "spike",
                "current_mb": round(current_mb, 1),
                "baseline_mb": round(baseline_mb, 1),
                "pct_increase": pct,
                "actual_ratio": round(spike["actual_ratio"], 2),
            },
        ))

    # 3. Drop
    drop_min_delta = config.min_drop_mb * _MB if config.min_drop_mb is not None else None
    drop = check_drop(
        short_avg=wa.short_avg,
        baseline_avg=wa.baseline_avg,
        ratio=config.drop_ratio,
        min_delta=drop_min_delta,
    )
    if drop is not None:
        results.append(_build_result(
            anomaly_type=f"{prefix}_drop",
            severity=drop["severity"],
            current=wa.current,
            baseline=wa.baseline_avg,
            window=config.duration,
            details={
                "mode": "drop",
                "current_mb": round(current_mb, 1),
                "baseline_mb": round(baseline_mb, 1),
                "actual_ratio": round(drop["actual_ratio"], 2),
                "drop_mb": round(drop["actual_delta"] / _MB, 1),
            },
        ))

    return results


def check_rss(
    history: deque,
    config: RssAnomalyConfig,
    sample_interval_sec: int = 5,
) -> list[dict]:
    """Check RSS anomalies across all 3 modes.

    Returns a list of 0–3 anomaly result dicts (ceiling, spike, drop).
    """
    return _check_rss_impl(
        history,
        config,
        sample_interval_sec,
        extract_metric=lambda s: s.rss_bytes,
        prefix="rss",
    )


def check_total_rss(
    history: deque,
    config: RssAnomalyConfig,
    sample_interval_sec: int = 5,
) -> list[dict]:
    """Check total RSS (process + children) anomalies across all 3 modes.

    Returns a list of 0–3 anomaly result dicts (ceiling, spike, drop).
    """
    return _check_rss_impl(
        history,
        config,
        sample_interval_sec,
        extract_metric=lambda s: s.total_rss_bytes,
        prefix="total_rss",
    )


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
