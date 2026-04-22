"""Sidecar app: graceful shutdown use case.

Handles SIGTERM/SIGINT cleanup per §7.7:
1. Mark shutdown_requested on session.
2. Drain central queue (up to drain_timeout_sec).
3. Close listening socket.
4. Unlink socket file.
"""
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from snitchbot.sidecar.session.domain.session_agg import SidecarSession

__all__ = ["GracefulShutdownUseCase"]


@dataclass(frozen=True, slots=True, kw_only=True)
class GracefulShutdownUseCase:
    """Shutdown sequence per §7.7.

    Callables are injected to keep this UC infrastructure-agnostic:
    - ``close_socket``: sync callable, closes the listening socket.
    - ``unlink_socket``: sync callable, unlinks the socket file.
    - ``drain_queue``: async callable, drains the central queue.
    """

    _session: SidecarSession
    _drain_timeout_sec: float = 5.0

    async def __call__(
        self,
        *,
        close_socket: Callable[[], None],
        unlink_socket: Callable[[], None],
        drain_queue: Callable[[], Awaitable[None]],
    ) -> None:
        # 1. Mark shutdown requested.
        self._session.request_shutdown()

        # 2. Drain central queue with timeout.
        try:
            await asyncio.wait_for(drain_queue(), timeout=self._drain_timeout_sec)
        except asyncio.TimeoutError:
            pass

        # 3. Close listening socket (invariant I5).
        close_socket()

        # 4. Unlink socket file (invariant I5).
        unlink_socket()
