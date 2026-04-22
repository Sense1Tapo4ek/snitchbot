"""InteractiveFacade — driving port for the interactive bounded context.

Delegates to StatusQuery, LastQuery, TestUC, TraceCallbackUC.
"""
from dataclasses import dataclass

from snitchbot.sidecar.interactive.app.interfaces import IRecentBuffer
from snitchbot.sidecar.interactive.app.use_cases.last_query import LastQuery
from snitchbot.sidecar.interactive.app.use_cases.status_query import StatusQuery
from snitchbot.sidecar.interactive.app.use_cases.test_uc import TestUC
from snitchbot.sidecar.interactive.app.use_cases.trace_callback_uc import TraceCallbackUC

__all__ = ["InteractiveFacade", "InteractiveSnapshot"]


@dataclass(frozen=True, slots=True, kw_only=True)
class InteractiveSnapshot:
    """Snapshot of interactive context state."""
    recent_event_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class InteractiveFacade:
    """Public driving port for the interactive bounded context.

    Methods map 1-to-1 to use cases; no business logic here.
    """

    _status_query: StatusQuery
    _last_query: LastQuery
    _test_uc: TestUC
    _trace_callback_uc: TraceCallbackUC
    _recent_buffer: IRecentBuffer | None

    async def status(self, *, args: str = "", now: float | None = None) -> dict:
        """Delegate to StatusQuery."""
        return await self._status_query(args=args, now=now)

    async def last(self, *, args: str = "", now: float | None = None) -> dict:
        """Delegate to LastQuery."""
        return await self._last_query(args=args, now=now)

    async def test(self, *, message_id: int | None = None, now: float | None = None) -> dict:
        """Delegate to TestUC."""
        return await self._test_uc(message_id=message_id, now=now)

    async def trace_callback(
        self,
        *,
        callback_query_id: str,
        fingerprint: str,
    ) -> None:
        """Delegate to TraceCallbackUC."""
        await self._trace_callback_uc(
            callback_query_id=callback_query_id,
            fingerprint=fingerprint,
        )

    def snapshot(self) -> InteractiveSnapshot:
        """Return a lightweight snapshot of current state."""
        count = len(self._recent_buffer) if self._recent_buffer is not None else 0
        return InteractiveSnapshot(recent_event_count=count)
