"""Muting app interfaces: all Protocols in one file.

S-DDD: driven port interfaces defined here; implementations in ports/driven/.
"""
from typing import Protocol

from snitchbot.sidecar.muting.domain.mute_state_agg import MuteEntry, MuteState

__all__ = ["ICommandBudget", "IMuteRepo", "ITelegramIOFacade"]


class ICommandBudget(Protocol):
    def acquire(self) -> bool: ...


class IMuteRepo(Protocol):
    """Persistence boundary for mute state (domain-first)."""

    async def save(self, state: MuteState) -> None:
        """Persist the active (non-expired) entries from the given state."""
        ...

    def load_entries(self) -> list[MuteEntry]:
        """Load previously persisted active (non-expired) entries.

        Returns an empty list if storage is absent or corrupted.
        """
        ...


class ITelegramIOFacade(Protocol):
    """Cross-context Protocol for the telegram_io driving facade (F7).

    Minimal surface — only reverse_lookup is needed by muting UCs to resolve
    the service name from a forum topic's ``message_thread_id``.
    """

    def reverse_lookup(self, message_thread_id: int) -> str | None:
        """Return the service bound to a thread id, or None."""
        ...
