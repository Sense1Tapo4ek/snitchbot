"""Ingest context: driving port facade."""
from dataclasses import dataclass

from snitchbot.sidecar.ingest.app.use_cases.register_client_uc import RegisterClientUseCase
from snitchbot.sidecar.ingest.domain.client_registry_agg import ClientRegistry

__all__ = ["IngestFacade", "IngestSnapshot"]


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestSnapshot:
    """Immutable snapshot of ingest context state."""

    client_count: int
    pids: tuple[int, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class IngestFacade:
    """Public API for the ingest bounded context."""

    _registry: ClientRegistry
    _register_uc: RegisterClientUseCase

    def register(self, *, hello: dict, sender_addr: str) -> dict:
        return self._register_uc(hello=hello, sender_addr=sender_addr)

    def snapshot(self) -> IngestSnapshot:
        clients = self._registry.clients_dict
        return IngestSnapshot(
            client_count=len(clients),
            pids=tuple(clients.keys()),
        )

    @property
    def clients_dict(self) -> dict:
        return self._registry.clients_dict
