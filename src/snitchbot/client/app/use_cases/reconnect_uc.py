"""Reconnect / respawn use case (Task 2.8).

Handles one reconnect attempt when in DEGRADED state.
Called periodically by the client module — this UC never sleeps or loops.

Spec refs: §8.1 (degraded recovery), §8.2 (exponential backoff).
Invariant: I7 — client in degraded mode periodically tries to recover.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from snitchbot.client.app.interfaces.i_discovery import IDiscovery
from snitchbot.client.app.interfaces.i_spawner import ISidecarSpawner
from snitchbot.client.app.interfaces.i_transport import ITransport
from snitchbot.client.domain.client_state_agg import ClientState
from snitchbot.client.domain.stats_vo import ClientStats
from snitchbot.client.ports.driven.discovery.flock_guard import flock_guard

__all__ = ["ReconnectUseCase", "compute_backoff"]

logger = logging.getLogger(__name__)

_BACKOFF_CAP = 30.0
_BACKOFF_SEQUENCE = [1.0, 2.0, 4.0, 8.0]


def compute_backoff(attempt: int) -> float:
    """Return retry delay in seconds for the given attempt number.

    Sequence per §8.2: 1 -> 2 -> 4 -> 8 -> 30 (capped).

    Args:
        attempt: Zero-based attempt counter.

    Returns:
        Seconds to wait before the next attempt.
    """
    if attempt < len(_BACKOFF_SEQUENCE):
        return _BACKOFF_SEQUENCE[attempt]
    return _BACKOFF_CAP


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconnectUseCase:
    """Attempt one reconnection to the sidecar.

    Caller is responsible for timing (no sleep here).
    Never raises — all exceptions are caught and DEGRADED is returned (P1/I7).
    """

    _transport: ITransport
    _discovery: IDiscovery
    _spawner: ISidecarSpawner
    _stats: ClientStats

    def __call__(
        self,
        *,
        service: str,
        token: str,
        chat_id: str | int,
        attempt: int,
        last_state: ClientState,
    ) -> ClientState:
        """Attempt to reconnect. Never raises.

        Returns:
            ClientState.CONNECTED on success, ClientState.DEGRADED on failure.
        """
        try:
            return self._attempt(service=service, token=token, chat_id=chat_id)
        except Exception:  # noqa: BLE001
            logger.debug("Reconnect attempt %d failed", attempt, exc_info=True)
            self._stats.sidecar_unavailable += 1
            return ClientState.DEGRADED

    def _attempt(
        self,
        *,
        service: str,
        token: str,
        chat_id: str | int,
    ) -> ClientState:
        """Inner attempt — may raise; wrapped by __call__."""
        socket_path: Path = self._discovery.compute_path(service, token, chat_id)
        lock_path = socket_path.parent / f"{socket_path.name}.lock"

        # Fast path: try connecting to existing socket.
        try:
            self._transport.connect(socket_path)
            if self._transport.is_connected:
                return ClientState.CONNECTED
        except Exception:
            # Optimistic connect failed — fall through to spawn path.
            logger.debug("reconnect: optimistic connect failed", exc_info=True)

        # Slow path: flock -> spawn -> connect.
        with flock_guard(lock_path):
            # Re-check after acquiring lock (another worker may have spawned).
            try:
                self._transport.connect(socket_path)
                if self._transport.is_connected:
                    return ClientState.CONNECTED
            except Exception:
                logger.debug("reconnect: post-flock connect failed", exc_info=True)

            # Try spawning a new sidecar.
            self._spawner.spawn(
                service=service,
                token=token,
                chat_id=chat_id,
                socket_path=socket_path,
                log_path=None,
            )

        # Post-spawn connect (outside the lock per §I6).
        self._transport.connect(socket_path)
        if self._transport.is_connected:
            return ClientState.CONNECTED

        self._stats.sidecar_unavailable += 1
        return ClientState.DEGRADED
