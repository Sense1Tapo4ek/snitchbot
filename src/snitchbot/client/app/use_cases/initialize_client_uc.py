"""Initialize client use case — discovery/spawn state machine (Task 2.6).

Orchestrates the full init() path per spec §5.2:
1. Compute socket path (via IDiscovery)
2. Optimistic connect — fast path, no flock (spec §5.2.2, I6)
3. If connect fails -> acquire flock -> re-check socket -> spawn sidecar if needed
4. After spawn -> poll for socket (up to SOCKET_POLL_TIMEOUT_SEC)
5. On any connect success -> perform hello handshake
6. On any failure -> transition to DEGRADED (never raise to user — I2, P1, P8, I9)

Invariants covered: I2, I3, I6, I8, I9, P1, P8.
"""
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from snitchbot.client.app.interfaces import IDiscovery, ISidecarSpawner, ITransport
from snitchbot.client.domain.client_state_agg import ClientState
from snitchbot.client.domain.stats_vo import ClientStats
from snitchbot.client.errors import HandshakeRejectedError, HandshakeTimeoutError
from snitchbot.client.ports.driven.discovery.flock_guard import flock_guard
from snitchbot.client.ports.driven.handshake.hello_service import build_hello, perform_handshake
from snitchbot.shared.constants import SOCKET_POLL_TIMEOUT_SEC
from snitchbot.shared.domain import AnomalyConfig
from snitchbot.shared.domain.services import compute_config_hash
from snitchbot.shared.generics.errors import PortError

__all__ = ["InitializeClientUseCase"]

logger = logging.getLogger("snitchbot.client.app.use_cases.initialize_client_uc")

# Poll granularity — how long to sleep between socket existence checks.
_POLL_SLEEP_SEC: float = 0.05


def _path_exists(path: Path) -> bool:
    """Return True if *path* exists on the filesystem."""
    return path.exists()


def _unlink_path(path: Path) -> None:
    """Unlink *path*, ignoring missing-file errors."""
    path.unlink(missing_ok=True)


def _poll_socket(path: Path, timeout_sec: float) -> bool:
    """Busy-poll until *path* appears or *timeout_sec* elapses.

    Returns True if the file appeared, False on timeout.
    """
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(_POLL_SLEEP_SEC)
    return path.exists()


@dataclass(frozen=True, slots=True, kw_only=True)
class InitializeClientUseCase:
    """Discovery/spawn state machine.

    Never raises from ``__call__``.  Returns ``CONNECTED`` on success,
    ``DEGRADED`` on any recoverable or unrecoverable failure.

    All dependencies are Protocols (injected via composition root).
    """

    _discovery: IDiscovery
    _transport: ITransport
    _spawner: ISidecarSpawner
    _stats: ClientStats

    def __call__(
        self,
        *,
        service: str,
        token: str,
        chat_id: str | int,
        anomaly_config: AnomalyConfig | None = None,
        role: str = "standalone",
    ) -> ClientState:
        """Run the init state machine.  Never raises.  Returns CONNECTED or DEGRADED."""
        try:
            return self._init_impl(
                service=service,
                token=token,
                chat_id=chat_id,
                anomaly_config=anomaly_config,
                role=role,
            )
        except Exception:
            logger.debug("init failed, entering degraded mode", exc_info=True)
            self._stats.internal_errors += 1
            return ClientState.DEGRADED

    # ------------------------------------------------------------------
    # Internal implementation — may raise; all callers are wrapped above
    # ------------------------------------------------------------------

    def _init_impl(
        self,
        *,
        service: str,
        token: str,
        chat_id: str | int,
        anomaly_config: AnomalyConfig | None,
        role: str = "standalone",
    ) -> ClientState:
        path = self._discovery.compute_path(service, token, chat_id)
        lock_path = path.with_suffix(".lock")

        # Step 1: Optimistic connect (no flock — I6, §5.2.2)
        try:
            self._transport.connect(path)
            return self._do_handshake(
                service=service, token=token, chat_id=chat_id,
                anomaly_config=anomaly_config, role=role,
            )
        except PortError:
            pass  # Socket not ready — proceed to slow path

        # Step 2: Acquire flock and re-check
        with flock_guard(lock_path):
            if _path_exists(path):
                # Another process may have spawned while we waited
                try:
                    self._transport.connect(path)
                    return self._do_handshake(
                        service=service, token=token, chat_id=chat_id,
                        anomaly_config=anomaly_config, role=role,
                    )
                except PortError:
                    # Stale socket — unlink and fall through to spawn
                    _unlink_path(path)

            # Step 3: Spawn sidecar
            self._spawner.spawn(
                service=service,
                token=token,
                chat_id=chat_id,
                socket_path=path,
                log_path=None,
            )
        # Flock released here (I6: lock not held at client runtime)

        # Step 4: Poll for socket (up to SOCKET_POLL_TIMEOUT_SEC)
        if not _poll_socket(path, SOCKET_POLL_TIMEOUT_SEC):
            return ClientState.DEGRADED

        # Step 5: Connect and handshake
        self._transport.connect(path)
        return self._do_handshake(
            service=service, token=token, chat_id=chat_id,
            anomaly_config=anomaly_config, role=role,
        )

    def _do_handshake(
        self,
        *,
        service: str,
        token: str,
        chat_id: str | int,
        anomaly_config: AnomalyConfig | None,
        role: str = "standalone",
    ) -> ClientState:
        """Execute hello handshake.  Returns CONNECTED or DEGRADED on handshake errors."""
        import time as _time

        resolved_anomaly = (
            anomaly_config if anomaly_config is not None else AnomalyConfig.defaults()
        )

        hello = build_hello(
            pid=os.getpid(),
            service=service,
            config_hash=compute_config_hash(token, str(chat_id)),
            started_at=_time.time(),
            anomaly_config=resolved_anomaly,
            role=role,
        )

        try:
            perform_handshake(
                transport_send=self._transport.send,
                transport_recv=self._transport.recv,  # type: ignore[attr-defined]
                hello_payload=hello,
            )
            return ClientState.CONNECTED
        except (HandshakeRejectedError, HandshakeTimeoutError):
            return ClientState.DEGRADED
