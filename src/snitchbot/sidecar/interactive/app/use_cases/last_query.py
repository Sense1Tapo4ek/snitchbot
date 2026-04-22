"""LastQuery — /last command handler."""
import time
from dataclasses import dataclass, field

from snitchbot.shared.constants import SEPARATOR, TG_MESSAGE_LIMIT
from snitchbot.shared.domain.services import fmt_window_label
from snitchbot.shared.domain.services import (
    WindowParseError,
    parse_window_seconds,
)
from snitchbot.sidecar.interactive.app.interfaces import (
    IRecentBuffer,
    ISidecarConfig,
    ITelegramIOFacade,
)
from snitchbot.sidecar.interactive.app.use_cases._service_scope import (
    resolve_service_scope,
)

__all__ = ["LastQuery"]

_DEFAULT_N = 5
_MAX_N = 20
_DEFAULT_WINDOW_SEC = 3600.0  # 1h
_DEFAULT_SEVERITIES = {"error", "critical"}
_MSG_LIMIT = TG_MESSAGE_LIMIT

_SEVERITY_ICON = {
    "error": "🔴",
    "critical": "🟣",
    "warning": "🟠",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class LastQuery:
    """Query use case for /last command.

    Dependencies:
        _recent_buffer  : RecentEventsBuffer
        _config         : SidecarConfig
        _button_builder : callable(fingerprint) -> dict | None  (optional)
    """

    _recent_buffer: IRecentBuffer
    _config: ISidecarConfig
    _telegram_io: ITelegramIOFacade | None = field(default=None)

    async def __call__(
        self,
        *,
        args: str = "",
        now: float | None = None,
        message_thread_id: int | None = None,
    ) -> dict:
        """Execute /last query.

        Args:
            args: raw argument string (e.g. "10 24h all")
            now:  override current time (for tests)
            message_thread_id: forum topic id the command arrived on (None
                outside forum mode). F7: resolved to a service name that is
                shown in the rendered header.

        Returns:
            {"text": <HTML str>, "parse_mode": "HTML"}
        """
        if now is None:
            now = time.time()

        # F7: resolve service scope from forum topic
        scope_service = resolve_service_scope(self._telegram_io, message_thread_id)

        # Parse arguments
        n = _DEFAULT_N
        window_sec = _DEFAULT_WINDOW_SEC
        include_warnings = False

        for token in args.split():
            if token == "all":
                include_warnings = True
            elif token.isdigit():
                n = min(int(token), _MAX_N)
            else:
                try:
                    window_sec = parse_window_seconds(token)
                except WindowParseError:
                    return {
                        "text": "❌ usage: /last [N] [window] [all]",
                        "parse_mode": "HTML",
                    }

        # Fetch recent events
        sevs = None if include_warnings else _DEFAULT_SEVERITIES
        events = self._recent_buffer.last_n(
            n=n,
            window_sec=window_sec,
            now=now,
            severities=sevs,
        )

        window_label = fmt_window_label(window_sec)
        service = scope_service or self._config.service

        if not events:
            kind = "errors" if not include_warnings else "events"
            return {
                "text": f"📋 No {kind} in last {window_label}.",
                "parse_mode": "HTML",
            }

        header = f"📋 <b>Last {len(events)} errors</b> · {service} · window {window_label}"
        cards = self._render_cards(events)
        full_text = f"{header}\n{SEPARATOR}\n" + "\n\n".join(cards)

        # Truncate at 4096 if needed
        if len(full_text) > _MSG_LIMIT:
            truncated = full_text[:_MSG_LIMIT - 30]
            full_text = truncated + "\n… entries truncated"

        return {"text": full_text, "parse_mode": "HTML"}

    def _render_cards(self, events: list) -> list[str]:
        cards = []
        for ev in events:
            icon = _SEVERITY_ICON.get(ev.severity or "", "⚪")
            fp = f"<code>{ev.fingerprint}</code>" if ev.fingerprint else "—"
            count_str = f" × {ev.count}" if ev.count > 1 else ""
            exc_type = ev.exception_type or "Event"
            msg = (ev.message or "")[:200]
            lines = [f"{icon} {fp}{count_str}", f"<b>{exc_type}</b>: {msg}"]

            # Inline buttons
            if ev.fingerprint:
                btn_row = _build_buttons(ev.fingerprint)
                lines.append(btn_row)

            cards.append("\n".join(lines))
        return cards


def _build_buttons(fp: str) -> str:
    """Placeholder inline button row (actual markup handled by gateway layer)."""
    return "[🔇 5m]  [🔇 1h]  [🔇 24h]  [📋 trace]"

