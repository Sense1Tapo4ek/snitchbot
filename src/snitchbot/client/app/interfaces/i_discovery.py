from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class IDiscovery(Protocol):
    def compute_path(self, service: str, token: str, chat_id: str | int) -> Path: ...
