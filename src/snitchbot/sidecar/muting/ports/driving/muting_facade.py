"""MutingFacade — driving port for the muting bounded context.

Thin delegation layer: no business logic, no branching beyond argument passing.
"""
from dataclasses import dataclass

from snitchbot.sidecar.muting.domain.mute_state_agg import MuteState

__all__ = ["MutingFacade", "MutingSnapshot", "MuteEntryView"]


@dataclass(frozen=True, slots=True, kw_only=True)
class MuteEntryView:
    """Read-only projection of a single active mute entry."""

    fingerprint: str | None
    muted_at: float
    duration_sec: float
    expires_at: float


@dataclass(frozen=True, slots=True, kw_only=True)
class MutingSnapshot:
    """Immutable snapshot of the current mute state."""

    active_count: int
    active_entries: tuple[MuteEntryView, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class MutingFacade:
    """Public API of the muting context.

    Callers outside this context must only interact via this facade.
    """

    _mute_state: MuteState
    _mute_uc: object
    _unmute_uc: object
    _mute_callback_uc: object
    _unmute_callback_uc: object

    async def mute(self, *, args: str, now: float | None = None) -> dict:
        """Execute /mute command. Returns reply dict."""
        return await self._mute_uc(args=args, now=now)  # type: ignore[operator]

    async def unmute(self, *, args: str, now: float | None = None) -> dict:
        """Execute /unmute command. Returns reply dict."""
        return await self._unmute_uc(args=args, now=now)  # type: ignore[operator]

    async def handle_mute_callback(
        self,
        *,
        callback_query_id: str,
        message_id: int,
        fingerprint: str,
        duration_str: str,
        now: float | None = None,
    ) -> None:
        """Handle mute inline-button callback."""
        await self._mute_callback_uc(  # type: ignore[operator]
            callback_query_id=callback_query_id,
            message_id=message_id,
            fingerprint=fingerprint,
            duration_str=duration_str,
            now=now,
        )

    async def handle_unmute_callback(
        self,
        *,
        callback_query_id: str,
        message_id: int,
        fingerprint: str,
        now: float | None = None,
    ) -> None:
        """Handle unmute inline-button callback."""
        await self._unmute_callback_uc(  # type: ignore[operator]
            callback_query_id=callback_query_id,
            message_id=message_id,
            fingerprint=fingerprint,
            now=now,
        )

    def is_muted(
        self,
        *,
        fingerprint: str | None,
        severity: str | None,
        now: float,
        service: str | None = None,
    ) -> bool:
        """Return True if the event should be suppressed.

        ``service`` (F7) — event's service in forum mode. ``None`` preserves
        simple-mode behaviour.
        """
        return self._mute_state.is_muted(
            fingerprint=fingerprint,
            severity=severity,
            now=now,
            service=service,
        )

    def snapshot(self, *, now: float) -> MutingSnapshot:
        """Return an immutable snapshot of the current mute state."""
        active = self._mute_state.get_active_mutes(now)
        views = tuple(
            MuteEntryView(
                fingerprint=e.fingerprint,
                muted_at=e.muted_at,
                duration_sec=e.duration_sec,
                expires_at=e.expires_at,
            )
            for e in active
        )
        return MutingSnapshot(active_count=len(views), active_entries=views)
