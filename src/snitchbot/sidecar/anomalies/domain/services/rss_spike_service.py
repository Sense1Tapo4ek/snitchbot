"""RSS spike anomaly detector.

Pure domain service — stdlib only, no I/O, no frameworks.
"""
from collections import deque

from snitchbot.shared.domain import RssSpikeConfig

__all__ = ["check_rss_spike"]

_MIN_HISTORY = 10

def check_rss_spike(
    history: deque,
    config: RssSpikeConfig,
) -> dict | None:
    """Check whether RSS has spiked relative to the rolling baseline.

    Triggers when BOTH conditions hold:
    - ``current_rss > baseline * config.ratio``
    - ``current_rss > baseline + config.min_delta_mb * 1024 * 1024``

    If ``current_rss > baseline * config.severity_upgrade_ratio``, severity is
    upgraded from ``'warning'`` to ``'error'`` (A7).

    Args:
        history: deque of VitalsSnapshot, most recent at the right end.
        config: RssSpikeConfig with ``ratio``, ``min_delta_mb``,
                ``severity_upgrade_ratio``.

    Returns:
        Anomaly result dict or ``None``.
    """
    if len(history) < _MIN_HISTORY:
        return None

    snaps = list(history)
    baseline: float = sum(s.rss_bytes for s in snaps) / len(snaps)
    current: int = snaps[-1].rss_bytes

    min_delta_bytes = config.min_delta_mb * 1024 * 1024
    if current <= baseline * config.ratio or current <= baseline + min_delta_bytes:
        return None

    severity = (
        "error"
        if current > baseline * config.severity_upgrade_ratio
        else "warning"
    )

    return {
        "anomaly_type": "rss_spike",
        "current": current,
        "baseline": baseline,
        "threshold_pct": (config.ratio - 1) * 100,
        "window": "5m",
        "severity": severity,
        "details": {
            "ratio_triggered": current / baseline if baseline > 0 else 0.0,
            "delta_bytes": current - baseline,
            "min_delta_bytes": min_delta_bytes,
        },
    }
