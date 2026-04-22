"""Muting app interfaces (Protocols)."""
from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway
from snitchbot.sidecar.muting.app.interfaces.i_muting_deps import ICommandBudget, IMuteRepo

__all__ = ["IMuteRepo", "ITelegramGateway", "ICommandBudget"]
