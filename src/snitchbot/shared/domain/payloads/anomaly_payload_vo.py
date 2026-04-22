"""Anomaly payload VO.

"""
from dataclasses import dataclass
from typing import Any, Literal

AnomalyType = Literal[
    # v2: 3-mode types (4 metrics × 3 modes)
    "rss_ceiling", "rss_spike", "rss_drop",
    "cpu_ceiling", "cpu_spike", "cpu_drop",
    "fds_ceiling", "fds_spike", "fds_drop",
    "threads_ceiling", "threads_spike", "threads_drop",
    # v1 deprecated aliases (kept for backward compat)
    "cpu_sustained", "fd_leak", "thread_growth",
]

@dataclass(frozen=True, slots=True, kw_only=True)
class AnomalyPayload:
    """Payload for ``EventKind.ANOMALY`` events (spec §4.5).

    Generated internally by the sidecar vitals sampler when a threshold is
    crossed; uses the same envelope format as other kinds for pipeline
    uniformity.
    """

    anomaly_type: AnomalyType
    current: float
    baseline: float
    threshold_pct: float
    window: str
    details: dict[str, Any]
