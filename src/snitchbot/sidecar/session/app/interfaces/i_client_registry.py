"""Session app: IClientRegistry protocol.

Defines only the methods TickIdleWatcherUseCase needs.
Concrete implementation lives in sidecar.domain.client_registry_agg (ingest context).
"""
from typing import Protocol

__all__ = ["IClientRegistry"]


class IClientRegistry(Protocol):
    """Minimal registry interface required by TickIdleWatcherUseCase."""

    def all_pids(self) -> list[int]: ...

    def get_by_pid(self, pid: int) -> object | None: ...

    def is_empty(self) -> bool: ...

    def remove(self, pid: int) -> None: ...
