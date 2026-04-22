"""Client app interfaces (Protocols). Implemented in ports/driven/."""

from .i_discovery import IDiscovery
from .i_spawner import ISidecarSpawner
from .i_transport import ITransport

__all__ = ["IDiscovery", "ISidecarSpawner", "ITransport"]
