"""UnmuteUC — /unmute command handler."""
import logging
import re
import time
from dataclasses import dataclass, field

from snitchbot.shared.constants import SEPARATOR
from snitchbot.shared.domain.services import fmt_window_label
from snitchbot.sidecar.muting.app.interfaces.i_muting_deps import (
    IMuteRepo,
    ITelegramIOFacade,
)
from snitchbot.sidecar.muting.app.use_cases.mute_uc import _resolve_service
from snitchbot.sidecar.muting.domain.mute_state_agg import MuteState

logger = logging.getLogger(__name__)
__all__ = ["UnmuteUC"]

_FP_RE = re.compile(r"^[0-9a-f]{6}$", re.IGNORECASE)


@dataclass(frozen=True, slots=True, kw_only=True)
class UnmuteUC:
    """Use case for /unmute command."""

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
        """Execute /unmute.

        Args:
            args: raw argument string e.g. "a1b2c3" or "all"
            now:  override current time (for tests)
            message_thread_id: forum topic id the command arrived on (None
                outside forum mode). F7: resolves to a service and unmutes
                only that service's scoped entry.

        Returns:
            {"text": ..., "parse_mode": "HTML"}
        """
        if now is None:
            now = time.time()

        # F7: resolve service from forum topic (None in General or simple mode)
        service = _resolve_service(self._telegram_io, message_thread_id)

        tokens = args.strip().split()
        if not tokens:
            return {
                "text": "❌ usage: /unmute <fingerprint|all>",
                "parse_mode": "HTML",
            }

        fp_token = tokens[0].lower()

        # Validate fingerprint
        fingerprint: str | None
        if fp_token == "all":
            fingerprint = None
        elif _FP_RE.match(fp_token):
            fingerprint = fp_token
        else:
            return {
                "text": "❌ Unknown fingerprint format (expect 6 hex chars)",
                "parse_mode": "HTML",
            }

        # Get entry before unmuting (for the reply) — service-scoped
        entry = self._mute_state.get_entry(fingerprint, service=service)

        if entry is None:
            if fingerprint is None:
                return {"text": "❌ No global mute active", "parse_mode": "HTML"}
            else:
                return {"text": f"❌ Not muted: {fingerprint}", "parse_mode": "HTML"}

        # Capture values before unmuting
        suppressed = entry.suppressed_count
        was_duration = entry.duration_sec
        remaining_sec = max(0.0, entry.expires_at - now)

        success = self._mute_state.unmute(fingerprint=fingerprint, service=service)
        if not success:
            if fingerprint is None:
                return {"text": "❌ No global mute active", "parse_mode": "HTML"}
            return {"text": f"❌ Not muted: {fingerprint}", "parse_mode": "HTML"}

        # Persist
        try:
            await self._mute_repo.save(self._mute_state)
        except Exception:
            logger.debug("unmute persist failed", exc_info=True)

        was_label = fmt_window_label(was_duration)
        remaining_label = (
            fmt_window_label(remaining_sec) if remaining_sec >= 60
            else f"{int(remaining_sec)}s"
        )

        if fingerprint is None:
            text = (
                f"🔔 <b>Global mute cancelled</b>\n{SEPARATOR}\n"
                f"was          muted {was_label}\n"
                f"remaining    {remaining_label} (cancelled)\n"
                f"suppressed   {suppressed} events during mute"
            )
        else:
            exc_type = entry.exception_type or fingerprint
            text = (
                f"🔔 <b>Unmuted</b>\n{SEPARATOR}\n"
                f"fingerprint  <code>{fingerprint}</code>\n"
                f"exception    {exc_type}\n"
                f"was          muted {was_label}\n"
                f"remaining    {remaining_label} (cancelled)\n"
                f"suppressed   {suppressed} events during mute"
            )

        return {"text": text, "parse_mode": "HTML"}

