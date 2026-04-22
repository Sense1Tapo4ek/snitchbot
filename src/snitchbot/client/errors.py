"""Client-side port errors."""

from snitchbot.shared.generics.errors import PortError


class HandshakeTimeoutError(PortError):
    """Hello handshake did not receive ack within HANDSHAKE_RESPONSE_TIMEOUT_MS."""


class HandshakeRejectedError(PortError):
    """Sidecar rejected hello due to config_hash mismatch or version mismatch."""

    def __init__(self, reason: str = "") -> None:
        self.reason = reason
        msg = (
            f"Handshake rejected by sidecar: {reason}" if reason
            else "Handshake rejected by sidecar"
        )
        super().__init__(msg)


class SocketPathError(PortError):
    """Failed to compute or validate the UNIX socket path."""


class SpawnFailedError(PortError):
    """subprocess.Popen failed to start the sidecar process."""


class TransportError(PortError):
    """Transport-level failure — connection or send error."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class BufferFullError(TransportError):
    """Send failed because the socket send buffer is full (EAGAIN / ENOBUFS)."""


class SidecarDeadError(TransportError):
    """Send failed because the sidecar process is no longer listening (BrokenPipe)."""
