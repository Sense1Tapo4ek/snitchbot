"""Protocols for cross-context command/callback handler callables.

telegram_io adapters receive UCs from other bounded contexts (interactive,
muting). These Protocols describe the minimal callable surface — adapters
depend on the Protocol, not the concrete UC class.
"""
from collections.abc import Awaitable, Callable
from typing import Protocol

__all__ = [
    "ICommandHandler",
    "ITestHandler",
    "IMuteCallbackHandler",
    "IUnmuteCallbackHandler",
    "ITraceCallbackHandler",
    "ICommandBudget",
    "ICommandRouter",
    "ICallbackRouter",
    "ISidecarSession",
    "SetCommandsFn",
]

# Type alias for the async no-arg callable passed to LongPollingController
SetCommandsFn = Callable[[], Awaitable[None]]


class ICommandHandler(Protocol):
    """Async command handler: /status, /last, /mute, /unmute.

    ``message_thread_id`` is the Telegram forum topic id the command arrived
    on (``None`` outside forum mode / for private chats). Handlers may ignore
    it; it is wired for F-T14 so use cases can scope state per topic.
    """

    async def __call__(
        self,
        *,
        args: str = "",
        now: float | None = None,
        message_thread_id: int | None = None,
    ) -> dict: ...


class ITestHandler(Protocol):
    """Async handler for /test (different signature — takes message_id).

    ``message_thread_id`` has the same semantics as in ``ICommandHandler``.
    """

    async def __call__(
        self,
        *,
        message_id: int | None = None,
        now: float | None = None,
        message_thread_id: int | None = None,
    ) -> dict: ...


class IMuteCallbackHandler(Protocol):
    """Async handler for mute inline-button callback."""

    async def __call__(
        self,
        *,
        callback_query_id: str,
        message_id: int,
        fingerprint: str,
        duration_str: str,
        now: float | None = None,
    ) -> None: ...


class IUnmuteCallbackHandler(Protocol):
    """Async handler for unmute inline-button callback."""

    async def __call__(
        self,
        *,
        callback_query_id: str,
        message_id: int,
        fingerprint: str,
        now: float | None = None,
    ) -> None: ...


class ITraceCallbackHandler(Protocol):
    """Async handler for trace inline-button callback."""

    async def __call__(
        self,
        *,
        callback_query_id: str,
        fingerprint: str,
    ) -> None: ...


class ICommandBudget(Protocol):
    """Token bucket for bot command rate-limiting."""

    def acquire(self) -> bool: ...

    def rate_limited_message(self, command: str) -> str: ...


class ICommandRouter(Protocol):
    """Routes Telegram slash-command messages to use cases."""

    async def handle(self, message: dict) -> None: ...


class ICallbackRouter(Protocol):
    """Routes inline-button callback queries to use cases."""

    async def handle(self, callback_query: dict) -> None: ...


class ISidecarSession(Protocol):
    """Minimal session surface used by the long-polling controller."""

    def mark_activity(self) -> None: ...
