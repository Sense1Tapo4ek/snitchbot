"""CPU sustained anomaly detector.

Pure domain service — stdlib only, no I/O, no frameworks.
"""
from collections import deque

from snitchbot.shared.domain import CpuSustainedConfig

__all__ = ["check_cpu_sustained"]

_MIN_HISTORY = 10

def check_cpu_sustained(
    history: deque,
    config: CpuSustainedConfig,
) -> dict | None:
    """Check whether CPU has been sustained above threshold for N consecutive samples.

    Triggers when the last ``config.samples`` consecutive samples all have
    ``cpu_percent > config.percent``.

    Args:
        history: deque of VitalsSnapshot, most recent at the right end.
        config: CpuSustainedConfig with ``percent`` and ``samples``.

    Returns:
        Anomaly result dict or ``None``.
    """
    if len(history) < _MIN_HISTORY:
        return None

    snaps = list(history)
    window = snaps[-config.samples:]
    if len(window) < config.samples:
        return None

    if not all(s.cpu_percent > config.percent for s in window):
        return None

    avg_cpu = sum(s.cpu_percent for s in window) / len(window)

    return {
        "anomaly_type": "cpu_sustained",
        "current": snaps[-1].cpu_percent,
        "baseline": float(config.percent),
        "threshold_pct": float(config.percent),
        "window": f"{config.samples} samples",
        "severity": "warning",
        "details": {
            "consecutive_samples": config.samples,
            "avg_cpu_percent": avg_cpu,
        },
    }
