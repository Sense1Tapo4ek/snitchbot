"""Live message updater workflow.

Invariants:
  LM1: one dashboard per (chat_id, thread_id) — one per topic in forum mode,
       one per chat in simple mode
  LM2: fixed 10s tick
  LM3: hash compare — no-op edits skipped
  LM4: lowest priority (callers control rate-bucket ordering; this workflow just renders)
  LM5: created only after first vitals sample
  LM6: graceful shutdown — final edit with red header and 'stopped at <time>'
  LM7: no persistence; new sidecar instance creates new message
  F8 : pinning failures (TG permission, network, any exception) are logged
       and swallowed — they never propagate out of a tick
"""
import hashlib
import logging
from dataclasses import dataclass, field

from snitchbot.shared.constants import SEPARATOR
from snitchbot.shared.domain import ClientState
from snitchbot.shared.domain.services import fmt_utc
from snitchbot.sidecar.live_message.app.interfaces import IRecentBuffer, ITelegramGateway
from snitchbot.sidecar.live_message.domain.live_message_state_agg import LiveMessageState
from snitchbot.sidecar.live_message.domain.services.live_message_render_service import (
    render_live_message,
)
from snitchbot.sidecar.telegram_io.ports.driving.telegram_io_facade import (
    TelegramIOFacade,
)

__all__ = ["LiveMessageUpdaterWorkflow", "LIVE_MESSAGE_TICK_SEC"]

logger = logging.getLogger("snitchbot.sidecar.live_message")

# LM2: fixed tick interval
LIVE_MESSAGE_TICK_SEC: int = 10

_5M_WINDOW = 5 * 60.0


def _content_hash(text: str) -> str:
    """Compute a short stable hash for change detection (LM3)."""
    return hashlib.md5(text.encode("utf-8"), usedforsecurity=False).hexdigest()

def _build_counters_from_buffer(
    recent_buffer: IRecentBuffer | None,
    now: float,
) -> dict[str, int]:
    """Extract last-5m counters from the recent events buffer.

    Falls back to zero-counters when buffer is not provided (e.g., in tests).
    """
    if recent_buffer is None:
        return {"errors": 0, "warnings": 0, "slow": 0, "anomaly": 0}

    window_sec = _5M_WINDOW
    # RecentEventsBuffer.traffic_counters returns errors/warnings/slow_calls/watchdog_hits
    raw = recent_buffer.traffic_counters(window_sec=window_sec, now=now)
    return {
        "errors": raw.get("errors", 0),
        "warnings": raw.get("warnings", 0),
        "slow": raw.get("slow_calls", 0),
        "anomaly": raw.get("anomaly", 0),
    }

def _group_clients_by_service(
    clients: dict[int, ClientState],
    fallback_service: str,
) -> dict[str, list[ClientState]]:
    """Group live client states by their service name.

    Dead clients are filtered by the render service itself; we keep them
    grouped here so that a "stale" service still sees its dashboard updated.
    A client with an empty service name falls back to ``fallback_service``
    (the sidecar's own service) so that vitals always land somewhere.
    """
    groups: dict[str, list[ClientState]] = {}
    for c in clients.values():
        if c.latest_vitals is None:
            continue
        svc = c.service or fallback_service
        groups.setdefault(svc, []).append(c)
    return groups


@dataclass(frozen=True, slots=True, kw_only=True)
class LiveMessageUpdaterWorkflow:
    """Maintain one pinned live dashboard per (chat_id, topic).

    In simple mode, ``resolve_topic`` returns ``None`` for every service, so
    all services fold into one entry keyed by ``(chat_id, None)`` — identical
    to the pre-forum-mode behaviour.

    In forum mode, each distinct service yields a distinct ``thread_id`` and
    an independent pinned dashboard.

    Responsibilities:
    - Render HTML from current client vitals + sidecar state
    - Create + pin message on first vitals sample per topic (LM5, F8)
    - Edit message when content changes; skip no-op edits (LM3)
    - Issue final shutdown edit with red header for every live dashboard (LM6)
    - Swallow pin failures so one topic's permission issue does not break
      another's dashboard (F8)
    """

    _gateway: ITelegramGateway
    _telegram_io: TelegramIOFacade
    _chat_id: str
    _service: str
    _state: LiveMessageState         # mutable in-memory state (LM1, LM7)
    _sidecar_started_at: float
    _recent_buffer: IRecentBuffer | None = field(default=None)

    async def tick(
        self,
        *,
        clients: dict[int, ClientState],
        now: float,
    ) -> None:
        """One live message update tick.

        Called every LIVE_MESSAGE_TICK_SEC seconds by the background loop.

        Args:
            clients: snapshot of current client states
            now:     current wall-clock time (injected for determinism in tests)
        """
        groups = _group_clients_by_service(clients, self._service)

        # LM5: do nothing until at least one vitals sample exists
        if not groups:
            return

        counters = _build_counters_from_buffer(self._recent_buffer, now)

        for service, service_clients in groups.items():
            await self._tick_one_service(
                service=service,
                service_clients=service_clients,
                counters=counters,
                now=now,
            )

    async def _tick_one_service(
        self,
        *,
        service: str,
        service_clients: list[ClientState],
        counters: dict[str, int],
        now: float,
    ) -> None:
        """Render + create-or-edit one (chat_id, topic) dashboard."""
        thread_id = await self._telegram_io.resolve_topic(service=service)

        rendered = render_live_message(
            service=service,
            clients=service_clients,
            sidecar_started_at=self._sidecar_started_at,
            counters=counters,
            now=now,
        )
        new_hash = _content_hash(rendered)

        message_id = self._state.get_message_id(self._chat_id, thread_id)

        if message_id is None:
            # LM5: first vitals for this topic — create + pin the message.
            new_id = await self._gateway.send_message(
                chat_id=self._chat_id,
                text=rendered,
                parse_mode="HTML",
                message_thread_id=thread_id,
            )
            self._state.set_message_id(self._chat_id, thread_id, new_id)
            self._state.set_created_at(self._chat_id, thread_id, now)
            self._state.set_content_hash(self._chat_id, thread_id, new_hash)

            # F8: pin failures must never propagate.
            try:
                await self._gateway.pin_chat_message(
                    chat_id=self._chat_id,
                    message_id=new_id,
                    disable_notification=True,
                )
            except Exception as exc:  # noqa: BLE001 — F8 swallows everything
                logger.warning(
                    "live_message: pin failed service=%s thread_id=%s msg_id=%s: %s",
                    service, thread_id, new_id, exc,
                )
            return

        # LM3: skip edit when content unchanged.
        if new_hash == self._state.get_content_hash(self._chat_id, thread_id):
            return

        # LM1: edit existing message (editMessageText ignores message_thread_id).
        await self._gateway.edit_message_text(
            chat_id=self._chat_id,
            message_id=message_id,
            text=rendered,
            parse_mode="HTML",
        )
        self._state.set_content_hash(self._chat_id, thread_id, new_hash)

    async def shutdown_edit(self, *, now: float) -> None:
        """Issue final red-header 'stopped at <time>' edit for every dashboard (LM6).

        No-op when no live messages exist. Iterates every known
        (chat_id, thread_id) entry so all topic dashboards get the final edit.
        """
        stopped_str = fmt_utc(now)

        for chat_id, _thread_id, entry in self._state.all_entries():
            if entry.message_id is None:
                continue
            text = (
                f"🔴 <b>{self._service}</b> · live\n"
                f"{SEPARATOR}\n"
                f"\n"
                f"<b>Sidecar</b>\n"
                f"  stopped at  {stopped_str}\n"
            )
            await self._gateway.edit_message_text(
                chat_id=chat_id,
                message_id=entry.message_id,
                text=text,
                parse_mode="HTML",
            )
