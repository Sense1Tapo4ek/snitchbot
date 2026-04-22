"""Private helper: resolve forum-topic message_thread_id -> service (F7).

Shared by every interactive UC that accepts ``message_thread_id``.
Returns None for General topic (thread_id None or 1), unknown thread ids
(silent fallback per F7), or simple mode.
"""
from snitchbot.sidecar.interactive.app.interfaces import ITelegramIOFacade

__all__ = ["resolve_service_scope"]


def resolve_service_scope(
    telegram_io: ITelegramIOFacade | None,
    message_thread_id: int | None,
) -> str | None:
    """Return service name bound to ``message_thread_id`` or None.

    * ``message_thread_id`` is None or 1 (General topic) -> None (global scope).
    * ``telegram_io`` is None (simple mode) -> None.
    * Thread id not registered -> None (silent fallback, F7).
    """
    if message_thread_id is None or message_thread_id == 1:
        return None
    if telegram_io is None:
        return None
    return telegram_io.reverse_lookup(message_thread_id)
