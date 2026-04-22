"""Socket path discovery — port layer wrapper (Task 2.1).

Thin wrapper that delegates to the shared kernel ``compute_socket_path``.
Implements :class:`~snitchbot.client.app.interfaces.i_discovery.IDiscovery`
and maps any unexpected exception into :class:`~snitchbot.client.errors.SocketPathError`.
"""
from pathlib import Path

from snitchbot.client.errors import SocketPathError
from snitchbot.shared.domain.services import compute_socket_path

__all__ = ["SocketPathDiscovery"]


class SocketPathDiscovery:
    """Implements IDiscovery by delegating to the shared kernel."""

    def compute_path(self, service: str, token: str, chat_id: str | int) -> Path:
        """Return the UNIX socket path for the given (service, token, chat_id) triple.

        Delegates to :func:`~snitchbot.shared.domain.services.config_hash_service.compute_socket_path`.

        Args:
            service: Logical service name.
            token: Telegram bot token.
            chat_id: Telegram chat id.

        Returns:
            Absolute :class:`~pathlib.Path` of the socket.

        Raises:
            SocketPathError: If the shared kernel raises for any reason.
        """
        try:
            return compute_socket_path(service, token, chat_id)
        except Exception as exc:
            raise SocketPathError(str(exc)) from exc
