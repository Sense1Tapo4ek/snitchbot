from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class ISidecarSpawner(Protocol):
    def spawn(
        self,
        *,
        service: str,
        token: str,
        chat_id: str | int,
        socket_path: Path,
        log_path: Path | None,
    ) -> int:
        """Spawn sidecar as a detached subprocess. Returns the child's PID."""
        ...
