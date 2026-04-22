"""Sidecar app: idle watcher use case.

Checks whether the sidecar should exit due to inactivity. Called
periodically by the event loop (§7.6 lifecycle_watcher).

Goodbye protocol: when a PID disappears without a prior lifecycle
shutdown event, emits a "killed" lifecycle event after a 2s grace
period (to avoid race conditions with in-flight IPC).
"""
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from snitchbot.sidecar.session.app.interfaces.i_client_registry import IClientRegistry
from snitchbot.sidecar.session.domain.session_agg import SidecarSession

__all__ = ["TickIdleWatcherUseCase"]

# Grace period before emitting "killed" — allows in-flight shutdown
# IPC to arrive (e.g. SIGTERM handler sent event but PID already reaped).
_KILLED_GRACE_SEC = 10.0


@dataclass(frozen=True, slots=True, kw_only=True)
class TickIdleWatcherUseCase:
    """Return True if sidecar should exit (idle timeout reached).

    Per §7.6:
    - Never exits before first hello has been received.
    - Probes each registered client via os.kill(pid, 0); removes dead ones.
    - Returns True only when registry is empty AND idle_seconds > idle_timeout_sec.

    Goodbye protocol:
    - If a client PID disappears and shutdown_received is False,
      waits _KILLED_GRACE_SEC then emits a "killed" lifecycle event.
    """

    _session: SidecarSession
    _registry: IClientRegistry
    _idle_timeout_sec: float = 30.0
    _on_client_killed: Callable[[int, str, str], None] | None = None

    def __call__(self) -> bool:
        if not self._session.first_hello_received:
            return False

        now = time.monotonic()

        for pid in self._registry.all_pids():
            if self._is_process_alive(pid):
                continue

            client = self._registry.get_by_pid(pid)
            if client is None:
                self._registry.remove(pid)
                continue

            if getattr(client, "shutdown_received", False):
                # Client sent a proper goodbye — just remove.
                self._registry.remove(pid)
                continue

            # PID dead, no goodbye. Apply grace period.
            dead_at = getattr(client, "dead_detected_at", None)
            if dead_at is None:
                # First detection — record timestamp, don't remove yet.
                client.dead_detected_at = now
                continue

            if now - dead_at < _KILLED_GRACE_SEC:
                # Within grace period — wait for in-flight IPC.
                continue

            # Re-check shutdown_received after grace period — IPC may
            # have arrived while we were waiting.
            if getattr(client, "shutdown_received", False):
                self._registry.remove(pid)
                continue

            # Grace period expired, no shutdown received -> emit killed.
            if self._on_client_killed is not None:
                service = getattr(client, "service", "")
                role = getattr(client, "role", "standalone")
                self._on_client_killed(pid, service, role)

            self._registry.remove(pid)

        if self._registry.is_empty() and self._session.idle_seconds() > self._idle_timeout_sec:
            return True

        return False

    @staticmethod
    def _is_process_alive(pid: int) -> bool:
        """Return True if the process is alive (os.kill signal 0)."""
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
