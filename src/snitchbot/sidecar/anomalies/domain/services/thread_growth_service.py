"""Thread growth anomaly detector.

Pure domain service — stdlib only, no I/O, no frameworks.
"""
from collections import deque

from snitchbot.shared.domain import ThreadGrowthConfig

__all__ = ["check_thread_growth"]

_MIN_HISTORY = 10

def check_thread_growth(
    history: deque,
    config: ThreadGrowthConfig,
) -> dict | None:
    """Check whether thread count has grown abnormally.

    Triggers when BOTH conditions hold:
    - ``current_threads > baseline + config.delta``
    - ``current_threads > baseline * config.ratio``

    Baseline is the rolling mean over the full history window.

    Args:
        history: deque of VitalsSnapshot, most recent at the right end.
        config: ThreadGrowthConfig with ``delta`` and ``ratio``.

    Returns:
        Anomaly result dict or ``None``.
    """
    if len(history) < _MIN_HISTORY:
        return None

    snaps = list(history)
    baseline: float = sum(s.threads for s in snaps) / len(snaps)
    current: int = snaps[-1].threads

    if current <= baseline + config.delta or current <= baseline * config.ratio:
        return None

    return {
        "anomaly_type": "thread_growth",
        "current": current,
        "baseline": baseline,
        "threshold_pct": (config.ratio - 1) * 100,
        "window": "5m",
        "severity": "warning",
        "details": {
            "delta_triggered": current - baseline,
            "min_delta": config.delta,
            "ratio_triggered": current / baseline if baseline > 0 else 0.0,
        },
    }
