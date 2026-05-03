"""Protocols for cross-context dependencies used by interactive app layer.

These define the minimal surface that StatusQuery, LastQuery, TestUC,
TraceCallbackUC and InteractiveFacade actually call — no concrete imports
from other bounded contexts.
"""
from typing import Protocol

from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway

__all__ = [
    "IClientInfo",
    "IClientRegistry",
    "IDedupEntry",
    "IDedupCache",
    "IEventQueue",
    "ICommandBudget",
    "IMuteState",
    "IRateBucket",
    "IRecentBuffer",
    "ISidecarConfig",
    "ISidecarSession",
    "ITelegramGateway",
    "ITelegramIOFacade",
]


class IClientInfo(Protocol):
    """Minimal client state surface used by StatusQuery."""

    role: str
    vitals_status: str
    latest_vitals: object | None
    last_seen: float


class IClientRegistry(Protocol):
    """Minimal registry surface used by StatusQuery / TestUC."""

    def all_pids(self) -> list[int]: ...

    def get_by_pid(self, pid: int) -> IClientInfo | None: ...


class ISidecarSession(Protocol):
    """Minimal session surface used by StatusQuery / TestUC."""

    started_at: float
    first_hello_received: bool
    dispatch_degraded: bool
    app_total_rss_bytes: int
    app_total_cpu_percent: float
    app_children_count: int


class IEventQueue(Protocol):
    """Central event queue — size inspection."""

    def __len__(self) -> int: ...

    @property
    def max_size(self) -> int: ...


class IDedupEntry(Protocol):
    """Minimal dedup entry surface used by TraceCallbackUC."""

    latest_event: dict


class IDedupCache(Protocol):
    """Dedup cache — size inspection + entry lookup."""

    def __len__(self) -> int: ...

    def get_entry(self, fingerprint: str) -> IDedupEntry | None: ...


class IRateBucket(Protocol):
    """Rate bucket — token inspection."""

    @property
    def tokens(self) -> float: ...

    @property
    def max_tokens(self) -> int: ...


class IMuteState(Protocol):
    """Mute state aggregate — active mutes query."""

    def get_active_mutes(self, now: float) -> list[object]: ...


class IRecentBuffer(Protocol):
    """Recent-events buffer — counter queries and listing."""

    def __len__(self) -> int: ...

    def traffic_counters(
        self,
        *,
        window_sec: float,
        now: float,
    ) -> dict[str, int]: ...

    def last_n(
        self,
        *,
        n: int,
        window_sec: float,
        now: float,
        severities: set[str] | None,
    ) -> list[object]: ...


class ICommandBudget(Protocol):
    """Command budget — acquire a slot."""

    def acquire(self) -> bool: ...


class ISidecarConfig(Protocol):
    """Minimal config surface used by interactive use cases."""

    service: str
    sidecar_service: str | None


class ITelegramIOFacade(Protocol):
    """Cross-context Protocol for the telegram_io driving facade (F7).

    Minimal surface — only reverse_lookup is needed by interactive UCs to
    resolve the service name from a forum topic's ``message_thread_id``.
    """

    def reverse_lookup(self, message_thread_id: int) -> str | None:
        """Return the service bound to a thread id, or None."""
        ...
