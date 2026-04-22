"""Sidecar app: register client use case.

Processes a hello datagram, validates config_hash, registers the client
in the registry, and returns an ack or reject dict.
"""
import logging
import math
import os
import time
from collections import deque as _deque
from dataclasses import dataclass

from snitchbot.shared.domain import AnomalyConfig
from snitchbot.shared.domain import ClientState
from snitchbot.sidecar.ingest.app.interfaces.i_recv_loop_deps import ISidecarSession
from snitchbot.sidecar.ingest.domain.client_registry_agg import ClientRegistry

_logger = logging.getLogger("snitchbot.sidecar.ingest")

try:
    from snitchbot import __version__ as _LIB_VERSION
except Exception:
    _LIB_VERSION = "0.0.0"

__all__ = ["RegisterClientUseCase"]


@dataclass(frozen=True, slots=True, kw_only=True)
class RegisterClientUseCase:
    """Process hello, register client, return ack or reject dict.

    Per §5.4:
    - If hello.config_hash != self._config_hash -> return reject (invariant I8).
    - Otherwise -> register client, mark first hello on session, return hello_ack.
    """

    _registry: ClientRegistry
    _session: ISidecarSession
    _config_hash: str  # expected config hash for this sidecar instance

    def __call__(self, *, hello: dict, sender_addr: str) -> dict:
        incoming_hash = hello.get("config_hash", "")
        if incoming_hash != self._config_hash:
            return {
                "type": "reject",
                "reason": "config_hash mismatch",
            }

        pid: int = hello["pid"]
        now = time.time()

        # Parse anomaly config dict -> AnomalyConfig VO (A3, A4).
        # Invalid config falls back to defaults — client validated on its side.
        try:
            anomaly_config = AnomalyConfig.from_dict(hello.get("anomaly_config"))
        except Exception:
            anomaly_config = AnomalyConfig.defaults()

        sample_interval = hello.get("sample_interval_sec", 5)

        client = ClientState(
            pid=pid,
            role=hello.get("role", "standalone"),
            service=hello.get("service", ""),
            last_seen=now,
            connected_at=hello.get("started_at", now),
            addr=sender_addr,
            config_hash=incoming_hash,
            anomaly_config=anomaly_config,
            sample_interval_sec=sample_interval,
        )

        # Size the vitals history deque based on the longest baseline_duration.
        max_history_sec = anomaly_config.max_history_seconds()
        required_maxlen = max(60, math.ceil(max_history_sec / sample_interval) + 1)
        if required_maxlen != 60:
            client.vitals_history = _deque(maxlen=required_maxlen)

        # Log estimated memory for vitals history
        est_bytes = required_maxlen * 120  # ~120 bytes per VitalsSnapshot
        if est_bytes >= 1024 * 1024:
            est_str = f"{est_bytes / (1024 * 1024):.1f} MB"
        else:
            est_str = f"{est_bytes / 1024:.0f} KB"
        _logger.warning(
            "Client PID=%d vitals: maxlen=%d, interval=%ds, est. memory ~%s",
            pid, required_maxlen, sample_interval, est_str,
        )

        self._registry.register(client)

        if not self._session.first_hello_received:
            self._session.mark_first_hello()
        else:
            self._session.mark_activity()

        return {
            "type": "hello_ack",
            "sidecar_pid": os.getpid(),
            "sidecar_lib_version": _LIB_VERSION,
            "client_id": pid,
        }
