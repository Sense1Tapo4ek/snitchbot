"""Sidecar domain: registered client registry.

Pure Python stdlib — no frameworks, no I/O.

``ClientState`` is the single source of truth for all per-client data.
The former ``RegisteredClient`` class has been removed; ``ClientRegistry``
now stores ``ClientState`` objects directly.
"""
from dataclasses import dataclass, field

from snitchbot.shared.domain import ClientState

__all__ = ["ClientRegistry", "ClientState"]


@dataclass(slots=True)
class ClientRegistry:
    """In-memory map of pid -> ClientState."""

    _clients: dict[int, ClientState] = field(default_factory=dict)

    def register(self, client: ClientState) -> None:
        """Add or update a client entry (idempotent on duplicate pid)."""
        self._clients[client.pid] = client

    def get_by_pid(self, pid: int) -> ClientState | None:
        return self._clients.get(pid)

    def remove(self, pid: int) -> None:
        self._clients.pop(pid, None)

    def is_empty(self) -> bool:
        return len(self._clients) == 0

    def all_pids(self) -> list[int]:
        return list(self._clients.keys())

    def all_states(self) -> list[ClientState]:
        """Return all mutable client states (for vitals sampling etc.)."""
        return list(self._clients.values())

    @property
    def clients_dict(self) -> dict[int, ClientState]:
        """Return the underlying pid->ClientState map (read-only reference).

        Exposed for workflows that need to iterate clients without copying —
        e.g. vitals sampler and live-message updater. Callers must not add
        or remove entries; use register()/remove() for that.
        """
        return self._clients
