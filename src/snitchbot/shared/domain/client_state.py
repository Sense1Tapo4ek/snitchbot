"""Mutable per-client sidecar state — shared kernel.

Moved from snitchbot.sidecar.ports.driven.vitals.psutil_vitals_sampler
so all contexts (anomalies, live_message, ingest, session, interactive)
can import it without cross-context coupling.

"""
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from snitchbot.shared.domain.vitals_snapshot_vo import VitalsSnapshot

__all__ = ["VitalsStatus", "ClientState"]

VitalsStatus = Literal["ok", "stale", "unavailable", "dead"]

@dataclass(slots=True)
class ClientState:
    """Per-client sidecar state — sampling + lifecycle fields.

    Spec §3.3. Mutable because the sampler loop updates it in-place.

    ``addr`` and ``config_hash`` are sourced from the hello handshake and were
    previously stored in the now-deleted ``RegisteredClient`` class.
    """

    pid: int
    role: str
    service: str
    last_seen: float
    connected_at: float

    # Registration metadata (from hello handshake)
    addr: str = field(default="")  # sender address for sendto replies
    config_hash: str = field(default="")  # validated config hash

    # Anomaly config — per-client, from hello handshake (A3, A4)
    anomaly_config: object = field(default=None)  # AnomalyConfig | None

    # Sampling interval in seconds — per-client, from hello handshake
    sample_interval_sec: int = field(default=5)

    # Vitals state (V2, V3, V4)
    psutil_process: object | None = field(default=None)
    psutil_create_time: float | None = field(default=None)
    latest_vitals: VitalsSnapshot | None = field(default=None)
    vitals_history: deque = field(default_factory=lambda: deque(maxlen=60))
    vitals_status: VitalsStatus = field(default="ok")
    fds_last_sampled_at: float = field(default=0.0)

    # Goodbye protocol: set True when client sends lifecycle shutdown event.
    # If PID disappears without this flag -> sidecar infers SIGKILL/OOM.
    shutdown_received: bool = field(default=False)
    # Monotonic timestamp when PID was first detected as dead (grace period).
    dead_detected_at: float | None = field(default=None)
