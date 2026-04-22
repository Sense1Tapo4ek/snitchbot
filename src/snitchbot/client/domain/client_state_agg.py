"""Client state machine enum.

Per spec: UNINITIALIZED before init, CONNECTED after successful handshake,
DEGRADED when sidecar unreachable but init succeeded, DISABLED when
init_conflict or hard failure.
"""

from enum import Enum


class ClientState(str, Enum):
    UNINITIALIZED = "uninitialized"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    DISABLED = "disabled"
