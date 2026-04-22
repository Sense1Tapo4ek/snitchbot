"""Protocols for cross-context dependencies used by live_message app layer."""
from typing import Protocol

from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway

__all__ = [
    "ITelegramGateway",
    "IRecentBuffer",
]


class IRecentBuffer(Protocol):
    """Recent-events buffer — counter queries used by live message tick."""

    def traffic_counters(
        self,
        *,
        window_sec: float,
        now: float,
    ) -> dict[str, int]: ...
