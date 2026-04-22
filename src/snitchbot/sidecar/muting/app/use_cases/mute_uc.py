"""MuteUC — /mute command handler."""
import logging
import re
import time
from dataclasses import dataclass, field

from snitchbot.shared.constants import SEPARATOR
from snitchbot.shared.domain.services import fmt_utc as _fmt_utc
from snitchbot.shared.domain.services import fmt_window_label
from snitchbot.shared.domain.services import (
    WindowParseError,
    parse_window_seconds,
)
from snitchbot.sidecar.muting.app.interfaces.i_muting_deps import (
    IMuteRepo,
    ITelegramIOFacade,
)
from snitchbot.sidecar.muting.domain.mute_state_agg import MuteState

logger = logging.getLogger(__name__)
__all__ = ["MuteUC"]

_FP_RE = re.compile(r"^[0-9a-f]{6}$", re.IGNORECASE)
_MAX_DURATION_SEC = 7 * 86400  # 7d


@dataclass(frozen=True, slots=True, kw_only=True)
class MuteUC:
    """Use case for /mute command."""

    _mute_state: MuteState
    _mute_repo: IMuteRepo
    _telegram_io: ITelegramIOFacade | None = field(default=None)

    async def __call__(
        self,
        *,
        args: str = "",
        now: float | None = None,
        message_thread_id: int | None = None,
    ) -> dict:
        """Execute /mute.

        Args:
            args: raw argument string e.g. "a1b2c3 1h" or "all 5m"
            now:  override current time (for tests)
            message_thread_id: forum topic id the command arrived on (None
                outside forum mode). F7: resolves to a service and scopes the
                mute so only that service's events are suppressed.

        Returns:
            {"text": ..., "parse_mode": "HTML"}
        """
        if now is None:
            now = time.time()

        # F7: resolve service from forum topic (None in General or simple mode)
        service = _resolve_service(self._telegram_io, message_thread_id)

        tokens = args.strip().split()
        if len(tokens) < 2:
            return {
                "text": "❌ usage: /mute <fingerprint|all> <duration>",
                "parse_mode": "HTML",
            }

        fp_token = tokens[0].lower()
        dur_token = tokens[1]

        # Validate fingerprint
        fingerprint: str | None
        if fp_token == "all":
            fingerprint = None
        elif _FP_RE.match(fp_token):
            fingerprint = fp_token
        else:
            return {
                "text": (
                    f"❌ Unknown fingerprint format: {fp_token!r}"
                    " (expect 6 hex chars or 'all')"
                ),
                "parse_mode": "HTML",
            }

        # Parse duration
        try:
            duration_sec = parse_window_seconds(dur_token)
        except WindowParseError:
            return {
                "text": f"❌ Invalid duration: {dur_token!r} — use 5m/1h/24h/7d",
                "parse_mode": "HTML",
            }

        if duration_sec > _MAX_DURATION_SEC:
            return {
                "text": "❌ Duration exceeds max (7d)",
                "parse_mode": "HTML",
            }

        # Apply mute (F7: service-scoped)
        success = self._mute_state.mute(
            fingerprint=fingerprint,
            duration_sec=duration_sec,
            source_message_id=None,
            now=now,
            service=service,
        )

        if not success:
            # Already muted — compute remaining
            entry = self._mute_state.get_entry(fingerprint, service=service)
            remaining_sec = int(entry.expires_at - now) if entry else 0
            remaining_min = max(1, remaining_sec // 60)
            return {
                "text": (
                    f"❌ Already muted for {int(duration_sec // 60)}m "
                    f"(expires in {remaining_min}m). Use /unmute first to override."
                ),
                "parse_mode": "HTML",
            }

        # Persist
        try:
            await self._mute_repo.save(self._mute_state)
        except Exception:
            logger.debug("mute persist failed", exc_info=True)

        # Build success reply
        expires_at = now + duration_sec
        expires_str = _fmt_utc(expires_at)
        dur_label = fmt_window_label(duration_sec)

        scope_line = f"scope        {service}\n" if service is not None else ""

        if fingerprint is None:
            text = (
                f"🔇 <b>Global mute</b>\n{SEPARATOR}\n"
                f"{scope_line}"
                f"duration     {dur_label}\n"
                f"expires      {expires_str} (in {dur_label})"
            )
        else:
            text = (
                f"🔇 <b>Muted</b>\n{SEPARATOR}\n"
                f"fingerprint  <code>{fingerprint}</code>\n"
                f"{scope_line}"
                f"duration     {dur_label}\n"
                f"expires      {expires_str} (in {dur_label})"
            )

        return {"text": text, "parse_mode": "HTML"}


def _resolve_service(
    telegram_io: ITelegramIOFacade | None,
    message_thread_id: int | None,
) -> str | None:
    """F7: translate a forum thread id to a service name.

    Returns None for General topic (thread_id is None or 1) or when the id is
    unknown — in which case the command falls back to global (simple-mode)
    behaviour (silent fallback, F7).
    """
    if message_thread_id is None or message_thread_id == 1:
        return None
    if telegram_io is None:
        return None
    return telegram_io.reverse_lookup(message_thread_id)
