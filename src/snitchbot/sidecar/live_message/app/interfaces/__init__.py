"""Live message app layer interfaces."""
from snitchbot.sidecar.live_message.app.interfaces.i_live_message_deps import (
    IRecentBuffer,
    ITelegramGateway,
)

__all__ = [
    "ITelegramGateway",
    "IRecentBuffer",
]
