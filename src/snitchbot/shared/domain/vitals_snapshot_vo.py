"""Immutable vitals snapshot value object — shared kernel.

Moved from snitchbot.sidecar.ports.driven.vitals.psutil_vitals_sampler
so all contexts (anomalies, live_message, ingest, session, interactive)
can import it without cross-context coupling.

"""
from dataclasses import dataclass

__all__ = ["VitalsSnapshot"]

@dataclass(frozen=True, slots=True, kw_only=True)
class VitalsSnapshot:
    """Immutable snapshot of one process vitals sample (spec §3.3).

    ``fds`` is ``None`` when:
    - FDs are not yet due for sampling (V9: 15s interval), OR
    - ``num_fds()`` raised ``AccessDenied`` (V8: per-metric degradation).
    """

    sampled_at: float
    rss_bytes: int
    cpu_percent: float
    threads: int
    fds: int | None
