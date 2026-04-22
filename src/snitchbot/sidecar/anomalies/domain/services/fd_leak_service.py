"""File-descriptor leak anomaly detector.

Pure domain service — stdlib only, no I/O, no frameworks.
"""
from collections import deque

from snitchbot.shared.domain import FdLeakConfig

__all__ = ["check_fd_leak"]

_MIN_HISTORY = 10

def check_fd_leak(
    history: deque,
    config: FdLeakConfig,
) -> dict | None:
    """Check whether file descriptors are monotonically growing (leak pattern).

    Triggers when ALL of the following hold over the last ``config.samples``:
    - Every sample's fds >= the previous sample's fds (monotonic growth).
    - ``current_fds > first_sample_in_window + config.min_delta``.

    Samples with ``fds=None`` (V8 degradation) are skipped — if ANY sample in
    the window has ``fds=None``, the detector returns ``None`` (insufficient data).

    Severity is always ``'error'`` (A7).

    Args:
        history: deque of VitalsSnapshot, most recent at the right end.
        config: FdLeakConfig with ``samples`` and ``min_delta``.

    Returns:
        Anomaly result dict or ``None``.
    """
    if len(history) < _MIN_HISTORY:
        return None

    snaps = list(history)
    window = snaps[-config.samples:]
    if len(window) < config.samples:
        return None

    # Skip window if any fds are None (V8: per-metric degradation)
    fd_values = [s.fds for s in window]
    if any(v is None for v in fd_values):
        return None

    first_fds: int = fd_values[0]  # type: ignore[assignment]
    current_fds: int = fd_values[-1]  # type: ignore[assignment]

    # Check monotonic growth
    for i in range(1, len(fd_values)):
        if fd_values[i] < fd_values[i - 1]:  # type: ignore[operator]
            return None

    # Check minimum delta
    if current_fds <= first_fds + config.min_delta:
        return None

    return {
        "anomaly_type": "fd_leak",
        "current": current_fds,
        "baseline": float(first_fds),
        "threshold_pct": 0.0,
        "window": f"{config.samples} samples",
        "severity": "error",
        "details": {
            "first_fds": first_fds,
            "delta": current_fds - first_fds,
            "min_delta": config.min_delta,
        },
    }
