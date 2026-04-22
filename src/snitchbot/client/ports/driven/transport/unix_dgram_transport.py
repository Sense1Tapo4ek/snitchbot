"""AF_UNIX SOCK_DGRAM transport port (driven).

Implements :class:`~snitchbot.client.app.interfaces.i_transport.ITransport`.
Wraps raw socket errors into specific :class:`TransportError` subclasses from
:mod:`snitchbot.client.errors`.
"""
import errno
import select
import socket
from pathlib import Path

from snitchbot.client.errors import BufferFullError, SidecarDeadError, TransportError


class UnixDgramTransport:
    """Non-blocking AF_UNIX SOCK_DGRAM transport.

    ``connect()`` creates a DGRAM socket and connects to the sidecar's bound
    path.  ``send()`` is non-blocking — on EAGAIN / ENOBUFS it raises
    :class:`BufferFullError`; on broken pipe it raises :class:`SidecarDeadError`;
    other failures raise :class:`TransportError`.
    """

    def __init__(self) -> None:
        self._sock: socket.socket | None = None

    # ------------------------------------------------------------------
    # ITransport implementation
    # ------------------------------------------------------------------

    def connect(self, path: Path) -> None:
        """Connect to the sidecar DGRAM socket at *path*.

        Raises :class:`TransportError` when the path does not exist or the
        OS rejects the connect call.
        """
        if not path.exists():
            raise TransportError(f"Socket path does not exist: {path}")

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.setblocking(False)
        try:
            sock.bind("")  # abstract namespace autobind — required for recv
            sock.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError, OSError) as exc:
            sock.close()
            raise TransportError(f"Connect failed: {exc}") from exc

        self._sock = sock

    def send(self, data: bytes) -> None:
        """Send *data* to the connected sidecar socket (non-blocking).

        Raises:
            BufferFullError: EAGAIN or ENOBUFS — send buffer exhausted.
            SidecarDeadError: BrokenPipe — sidecar process is gone.
            TransportError: any other send failure.
        """
        if self._sock is None:
            raise TransportError("Not connected")

        try:
            self._send(data)
        except BlockingIOError as exc:
            raise BufferFullError("Buffer full (EAGAIN)") from exc
        except BrokenPipeError as exc:
            self._sock = None
            raise SidecarDeadError("Sidecar dead (BrokenPipe)") from exc
        except OSError as exc:
            if exc.errno == errno.ENOBUFS:
                raise BufferFullError("No buffer space (ENOBUFS)") from exc
            raise TransportError(f"Send failed: {exc}") from exc

    def recv(self, timeout_ms: int) -> bytes | None:
        """Receive data with timeout. Returns None if no data within timeout.

        Requires connect() to have been called first (which autobinds via bind("")).
        The sidecar uses recvfrom to learn the client address and sendto to reply.

        Raises:
            TransportError: if not connected or OS error during recv.
        """
        if self._sock is None:
            raise TransportError("Not connected")
        timeout_sec = timeout_ms / 1000.0
        ready, _, _ = select.select([self._sock], [], [], timeout_sec)
        if not ready:
            return None
        try:
            data, _ = self._sock.recvfrom(65536)
            return data
        except OSError as exc:
            raise TransportError(f"Recv failed: {exc}") from exc

    def close(self) -> None:
        """Close the underlying socket if open; safe to call multiple times."""
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def _send(self, data: bytes) -> None:
        """Thin wrapper around socket.send — exists so tests can patch it."""
        if self._sock is None:
            raise TransportError("Not connected")
        self._sock.send(data)

    @property
    def is_connected(self) -> bool:
        """True when a socket is open and connected."""
        return self._sock is not None
