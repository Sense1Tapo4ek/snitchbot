"""Sidecar domain: sidecar session lifecycle state.

Pure Python stdlib — no frameworks, no I/O.
"""
import time
from dataclasses import dataclass

from snitchbot.shared.domain import ClientState

__all__ = ["SidecarSession"]


@dataclass(slots=True)
class SidecarSession:
    """Lifecycle state of a single sidecar instance."""

    started_at: float
    first_hello_received: bool = False
    shutdown_requested: bool = False
    last_activity_at: float = 0.0
    dispatch_degraded: bool = False
    app_total_rss_bytes: int = 0
    app_total_cpu_percent: float = 0.0
    app_children_count: int = 0

    def __post_init__(self) -> None:
        if self.last_activity_at == 0.0:
            self.last_activity_at = self.started_at

    def mark_activity(self) -> None:
        """Update last_activity_at to now."""
        self.last_activity_at = time.monotonic()

    def mark_first_hello(self) -> None:
        """Record that at least one hello has been processed."""
        self.first_hello_received = True
        self.mark_activity()

    def idle_seconds(self) -> float:
        """Seconds elapsed since last recorded activity."""
        return time.monotonic() - self.last_activity_at

    def request_shutdown(self) -> None:
        """Mark that a graceful shutdown has been requested."""
        self.shutdown_requested = True

    def update_app_totals(self, clients: list[ClientState]) -> None:
        """Sum total_* metrics across all live (non-dead) clients."""
        total_rss = 0
        total_cpu = 0.0
        total_children = 0
        for client in clients:
            if client.vitals_status == "dead":
                continue
            vitals = client.latest_vitals
            if vitals is not None:
                total_rss += vitals.total_rss_bytes
                total_cpu += vitals.total_cpu_percent
                total_children += vitals.children_count
        self.app_total_rss_bytes = total_rss
        self.app_total_cpu_percent = total_cpu
        self.app_children_count = total_children
