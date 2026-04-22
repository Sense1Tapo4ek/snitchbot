"""Send event use case (Task 2.7).

Pipeline: validate -> truncate -> pack -> send.

Spec:
- ``docs/superpowers/specs/2026-04-11-public-api-design.md`` §4.1 (notify), §11 (P1, P5)
- ``docs/superpowers/specs/2026-04-11-event-model-design.md`` §7 (truncation), §8 (validation)

Invariants covered:
- **P1** — never raises to caller; all errors caught, stats incremented.
- **P5** — non-blocking; transport.send is always called directly (no waiting).
- **I3** — stats counters reflect every outcome.
- **I9** — unexpected exceptions are silently counted as internal_errors.
"""
import logging
from dataclasses import dataclass

from snitchbot.client.app.interfaces.i_transport import ITransport
from snitchbot.client.domain.stats_vo import ClientStats
from snitchbot.client.errors import BufferFullError, SidecarDeadError, TransportError
from snitchbot.shared.domain.services import truncate_if_oversized
from snitchbot.shared.domain.services import validate
from snitchbot.shared.ports.driven.codec.i_codec import IMsgpackCodec

logger = logging.getLogger("snitchbot.client.app.use_cases.send_event_uc")


@dataclass(frozen=True, slots=True, kw_only=True)
class SendEventUseCase:
    """Send a single event dict to the sidecar.

    Never raises (P1, I9). All outcomes are recorded in ``_stats``.
    """

    _transport: ITransport
    _codec: IMsgpackCodec
    _stats: ClientStats

    def __call__(self, event_dict: dict) -> None:
        """Send an event to the sidecar. Never raises (P1, I3, I9).

        Pipeline:
        1. Validate -> if invalid, increment stats.invalid_events, return
        2. Truncate if oversized -> if still oversized, increment stats.oversized, return
        3. Pack via codec
        4. Send via transport -> on success increment stats.events_sent
                              -> TransportError("Buffer full*") -> stats.dropped_buffer_full
                              -> TransportError("Sidecar dead*") -> stats.sidecar_dead
                              -> any other error -> stats.internal_errors
        """
        try:
            self._pipeline(event_dict)
        except Exception:  # noqa: BLE001
            logger.debug("send_event pipeline error", exc_info=True)
            self._stats.internal_errors += 1

    # ------------------------------------------------------------------
    # Internal pipeline (may raise — outer try/except catches everything)
    # ------------------------------------------------------------------

    def _pipeline(self, event_dict: dict) -> None:
        # Step 1: validate
        errors = validate(event_dict)
        if errors:
            self._stats.invalid_events += 1
            return

        # Step 2: truncate if oversized
        result = truncate_if_oversized(event_dict, self._codec.size_of)
        if result is None:
            self._stats.oversized += 1
            return

        # Step 3: pack
        data = self._codec.pack(result)

        # Step 4: send (non-blocking — transport handles the socket flags)
        try:
            self._transport.send(data)
        except BufferFullError:
            self._stats.dropped_buffer_full += 1
            return
        except SidecarDeadError:
            self._stats.sidecar_dead += 1
            return
        except TransportError:
            self._stats.internal_errors += 1
            return

        self._stats.events_sent += 1
