"""Session context: driving port (facade).

SessionFacade is the public API of the session bounded context.
It delegates to domain and use cases — no business logic here.
"""
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from snitchbot.sidecar.session.app.use_cases.graceful_shutdown_uc import GracefulShutdownUseCase
from snitchbot.sidecar.session.app.use_cases.tick_idle_watcher_uc import TickIdleWatcherUseCase
from snitchbot.sidecar.session.domain.session_agg import SidecarSession

__all__ = ["SessionFacade", "SessionSnapshot"]


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionSnapshot:
    """Immutable snapshot of session state for external consumers."""

    started_at: float
    first_hello_received: bool
    shutdown_requested: bool
    last_activity_at: float
    idle_seconds: float


@dataclass(frozen=True, slots=True, kw_only=True)
class SessionFacade:
    """Public API for the session bounded context."""

    _session: SidecarSession
    _tick_idle_uc: TickIdleWatcherUseCase
    _graceful_shutdown_uc: GracefulShutdownUseCase

    def mark_activity(self) -> None:
        """Record activity on the session."""
        self._session.mark_activity()

    def mark_first_hello(self) -> None:
        """Record that the first hello has been received."""
        self._session.mark_first_hello()

    def tick_idle(self) -> bool:
        """Return True if sidecar should exit due to idle timeout."""
        return self._tick_idle_uc()

    async def shutdown(
        self,
        *,
        close_socket: Callable[[], None],
        unlink_socket: Callable[[], None],
        drain_queue: Callable[[], Awaitable[None]],
    ) -> None:
        """Run the graceful shutdown sequence."""
        await self._graceful_shutdown_uc(
            close_socket=close_socket,
            unlink_socket=unlink_socket,
            drain_queue=drain_queue,
        )

    def snapshot(self) -> SessionSnapshot:
        """Return an immutable snapshot of the current session state."""
        return SessionSnapshot(
            started_at=self._session.started_at,
            first_hello_received=self._session.first_hello_received,
            shutdown_requested=self._session.shutdown_requested,
            last_activity_at=self._session.last_activity_at,
            idle_seconds=self._session.idle_seconds(),
        )
