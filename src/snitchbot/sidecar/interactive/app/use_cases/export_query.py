"""ExportQuery — /export command use case.

Exports full vitals history as a CSV file sent via Telegram sendDocument.

Usage: /export
"""
import time as _time
from dataclasses import dataclass, field

from snitchbot.shared.constants import SEPARATOR
from snitchbot.sidecar.interactive.app.interfaces import ITelegramIOFacade
from snitchbot.sidecar.interactive.app.use_cases._service_scope import (
    resolve_service_scope,
)
from snitchbot.sidecar.interactive.domain.services.chart_data_service import (
    export_vitals_csv,
)

__all__ = ["ExportQuery"]


@dataclass(frozen=True, slots=True, kw_only=True)
class ExportQuery:
    """Exports all vitals data as CSV file via Telegram."""

    _registry: object  # IClientRegistry
    _gateway: object   # ITelegramGateway (with send_document)
    _chat_id: str
    _telegram_io: ITelegramIOFacade | None = field(default=None)

    async def __call__(
        self,
        *,
        args: str = "",
        now: float | None = None,
        message_thread_id: int | None = None,
    ) -> dict:
        """Handle /export command. Sends CSV file, returns status reply.

        ``message_thread_id`` is the forum topic id the command arrived on
        (None outside forum mode). F7: resolved to a service name; the CSV
        is exported from the first live client whose ``service`` matches.
        """
        if now is None:
            now = _time.monotonic()

        # F7: resolve service scope from forum topic
        scope_service = resolve_service_scope(self._telegram_io, message_thread_id)

        client = self._find_live_client(service=scope_service)
        if client is None:
            return {
                "text": (
                    f"📂 <b>export</b>\n{SEPARATOR}\n"
                    f"No live clients with vitals data."
                ),
                "parse_mode": "HTML",
            }

        history = client.vitals_history
        # Export all data — window_sec covers entire deque
        max_age = (now - history[0].sampled_at + 60) if history else 0
        mono_offset = _time.time() - now
        csv_text = export_vitals_csv(
            history, window_sec=max_age, now=now,
            mono_to_wall_offset=mono_offset,
        )
        csv_bytes = csv_text.encode("utf-8")

        service = getattr(client, "service", "snitchbot")
        filename = f"{service}_vitals.csv"
        line_count = csv_text.count("\n") - 1  # minus header

        await self._gateway.send_document(
            chat_id=self._chat_id,
            document=csv_bytes,
            filename=filename,
            caption=f"Vitals export: {line_count} samples",
        )

        return {
            "text": (
                f"📂 <b>export</b> · {service}\n{SEPARATOR}\n"
                f"Exported {line_count} samples."
            ),
            "parse_mode": "HTML",
        }

    def _find_live_client(self, *, service: str | None = None) -> object | None:
        """Return first ``ok`` client; filtered by ``service`` when set (F7)."""
        for pid in self._registry.all_pids():
            client = self._registry.get_by_pid(pid)
            if client is None or getattr(client, "vitals_status", "") != "ok":
                continue
            if service is not None and getattr(client, "service", None) != service:
                continue
            return client
        return None
