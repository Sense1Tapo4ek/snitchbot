"""AF_UNIX SOCK_DGRAM listening socket for the sidecar."""
import errno
import os
import socket
from pathlib import Path


class ListeningSocket:
    """Binds and owns an AF_UNIX SOCK_DGRAM socket at *path*."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._sock: socket.socket | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def bind(self) -> None:
        """Create, bind, and chmod the socket.

        Steps (per §7.1 startup sequence):
        1. Ensure parent directory exists with mode 0700 (§6.4).
        2. Unlink any stale socket file (§8.3).
        3. Create AF_UNIX SOCK_DGRAM socket.
        4. bind() — on EADDRINUSE another sidecar won the race -> SystemExit(0) (§7.1).
        5. chmod 0600 (§6.4).
        """
        self._path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._path.unlink(missing_ok=True)

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        try:
            self._sock.bind(str(self._path))
        except OSError as exc:
            if exc.errno == errno.EADDRINUSE:
                # Another sidecar won the race — exit gracefully (§7.1)
                self._sock.close()
                self._sock = None
                raise SystemExit(0) from exc
            raise

        os.chmod(str(self._path), 0o600)

    def close(self) -> None:
        """Close the socket (idempotent)."""
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def unlink(self) -> None:
        """Remove the socket file (missing_ok)."""
        self._path.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    def recvfrom(self, bufsize: int = 65536) -> tuple[bytes, str]:
        """Blocking receive.

        Returns:
            (data, sender_address) where sender_address is a str path or "".
        """
        if self._sock is None:
            raise RuntimeError("Socket is not bound")
        data, addr = self._sock.recvfrom(bufsize)
        return data, addr  # addr is already a str for AF_UNIX

    def sendto(self, data: bytes, addr: str) -> None:
        """Send *data* to *addr* (client's socket path)."""
        if self._sock is None:
            raise RuntimeError("Socket is not bound")
        self._sock.sendto(data, addr)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def fileno(self) -> int:
        """Return the underlying file descriptor, or -1 if not bound."""
        return self._sock.fileno() if self._sock is not None else -1
