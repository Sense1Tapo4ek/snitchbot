"""Vitals sampler workflow — orchestrates sampling + anomaly detection.

"""
import time
from collections.abc import Callable
from dataclasses import dataclass

from snitchbot import __version__
from snitchbot.shared.domain import ClientState
from snitchbot.sidecar.anomalies.app.interfaces.i_vitals_sampler import IVitalsSampler
from snitchbot.sidecar.anomalies.domain.services import (
    check_cpu,
    check_fds,
    check_rss,
    check_threads,
)

__all__ = ["VitalsSamplerWorkflow"]

# Minimum history depth before any anomaly check runs (A1 guard, spec §4.4)
_MIN_ANOMALY_HISTORY = 3

@dataclass(frozen=True, slots=True, kw_only=True)
class VitalsSamplerWorkflow:
    """Orchestrates: sample clients -> check anomalies -> enqueue events.

    One call to ``run_sampling_tick`` covers one full sampling round for all
    registered clients.

    ``_enqueue_anomaly`` is the callable that puts anomaly result dicts into
    the central event queue. Injected as a dependency so flow tests can mock it.
    """

    _enqueue_anomaly: Callable[[dict], None]
    _sampler: IVitalsSampler
    _sample_interval_sec: int = 5

    def run_sampling_tick(
        self, clients: dict[int, ClientState], *, now: float
    ) -> None:
        """Sample all clients and run anomaly detection for each.

        Iterates over a snapshot of client values (V5 — concurrent safe).
        After each successful sample, check_anomalies is called (A1).
        """
        for client in list(clients.values()):
            self._process_client(client, now=now)

    def _process_client(self, client: ClientState, *, now: float) -> None:
        """Sample one client and check anomalies. Handles errors per V5/V6/V7."""
        self._sampler.sample_into_state(client, now=now)
        if client.vitals_status == "ok":
            self._check_anomalies(client)

    def _check_anomalies(self, client: ClientState) -> None:
        """Run all four detectors for a client (A1, A2).

        Each detector returns a list of 0-3 results (ceiling/spike/drop).
        Each result is wrapped in an envelope and enqueued.
        """
        history = client.vitals_history
        if len(history) < _MIN_ANOMALY_HISTORY:
            return

        anomaly_config = client.anomaly_config
        if anomaly_config is None:
            return

        sample_sec = self._sample_interval_sec

        detectors = [
            (anomaly_config.rss, check_rss),
            (anomaly_config.cpu, check_cpu),
            (anomaly_config.fds, check_fds),
            (anomaly_config.threads, check_threads),
        ]

        for detector_cfg, detector_fn in detectors:
            if detector_cfg is None:
                continue  # A3: detector disabled for this client
            results = detector_fn(history, detector_cfg, sample_sec)
            for result in results:
                self._enqueue_anomaly(self._build_envelope(client, result))

    @staticmethod
    def _build_envelope(client: ClientState, result: dict) -> dict:
        """Wrap a detector result into a full event envelope."""
        return {
            "v": __version__,
            "ts": time.time(),
            "kind": "anomaly",
            "severity": result.get("severity", "warning"),
            "pid": client.pid,
            "trace_id": None,
            "context": None,
            "payload": {
                "anomaly_type": result.get("anomaly_type"),
                "current": result.get("current"),
                "baseline": result.get("baseline"),
                "threshold_pct": result.get("threshold_pct"),
                "window": result.get("window"),
                "details": result.get("details", {}),
            },
        }
