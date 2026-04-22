"""AnomaliesFacade — driving port for the anomalies bounded context."""
from dataclasses import dataclass

from snitchbot.shared.domain import ClientState
from snitchbot.sidecar.anomalies.app.workflows.vitals_sampler_workflow import (
    VitalsSamplerWorkflow,
)

__all__ = ["AnomaliesFacade"]


@dataclass(frozen=True, slots=True, kw_only=True)
class AnomaliesFacade:
    """Thin driving port — delegates sampling tick to the workflow."""

    _workflow: VitalsSamplerWorkflow

    def tick(self, clients: dict[int, ClientState], *, now: float) -> None:
        """Run one full sampling + anomaly detection tick over all clients."""
        self._workflow.run_sampling_tick(clients, now=now)
