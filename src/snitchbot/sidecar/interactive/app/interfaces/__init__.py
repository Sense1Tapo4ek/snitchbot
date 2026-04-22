"""Interactive app layer interfaces."""
from snitchbot.sidecar.interactive.app.interfaces.i_status_deps import (
    IClientInfo,
    IClientRegistry,
    ICommandBudget,
    IDedupCache,
    IDedupEntry,
    IEventQueue,
    IMuteState,
    IRateBucket,
    IRecentBuffer,
    ISidecarConfig,
    ISidecarSession,
    ITelegramGateway,
    ITelegramIOFacade,
)

__all__ = [
    "IClientInfo",
    "IClientRegistry",
    "ICommandBudget",
    "IDedupCache",
    "IDedupEntry",
    "IEventQueue",
    "IMuteState",
    "IRecentBuffer",
    "IRateBucket",
    "ISidecarConfig",
    "ISidecarSession",
    "ITelegramGateway",
    "ITelegramIOFacade",
]
