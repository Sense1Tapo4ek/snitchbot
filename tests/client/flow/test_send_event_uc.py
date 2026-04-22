"""Flow tests for SendEventUseCase (Task 2.7).

Tests cover (per plan):
- test_send_valid_event_increments_events_sent — happy path
- test_send_validates_first — invalid event -> stats.invalid_events incremented, transport.send NOT called
- test_send_truncates_oversized_then_sends — oversized event gets truncated, truncated version sent
- test_send_drops_still_oversized_increments_stats — truncation returns None -> stats.oversized incremented
- test_send_buffer_full_increments_dropped — transport raises buffer full -> stats.dropped_buffer_full
- test_send_broken_pipe_increments_sidecar_dead — transport raises broken pipe -> stats.sidecar_dead
- test_send_never_raises_to_caller — any unexpected exception -> caught, stats.internal_errors (P1, I9)
- test_send_non_blocking — verify transport.send called (non-blocking is a transport property)

Invariants: P1 (never raises), P5 (non-blocking), I3, I9.
"""

from unittest.mock import MagicMock, patch

import pytest

from snitchbot import __version__
from snitchbot.client.app.use_cases.send_event_uc import SendEventUseCase
from snitchbot.client.domain.stats_vo import ClientStats
from snitchbot.client.errors import BufferFullError, SidecarDeadError, TransportError

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_VALID_EVENT: dict = {
    "v": __version__,
    "kind": "crash",
    "severity": "error",
    "ts": 1_700_000_000.0,
    "pid": 1234,
    "trace_id": None,
    "context": None,
    "payload": {"message": "boom"},
}


def _make_uc(
    transport=None,
    codec=None,
    stats=None,
) -> tuple[SendEventUseCase, MagicMock, MagicMock, ClientStats]:
    if transport is None:
        transport = MagicMock()
        transport.send.return_value = None
    if codec is None:
        codec = MagicMock()
        codec.pack.return_value = b"\x80"
        codec.size_of.return_value = 10  # small — fits
    if stats is None:
        stats = ClientStats()
    uc = SendEventUseCase(_transport=transport, _codec=codec, _stats=stats)
    return uc, transport, codec, stats


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSendValidEvent:
    def test_send_valid_event_increments_events_sent(self):
        """
        Given a valid event dict,
        When SendEventUseCase is called,
        Then stats.events_sent is incremented by 1 and transport.send is called once.
        """
        # Arrange
        uc, transport, codec, stats = _make_uc()

        with (
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.validate",
                return_value=[],
            ),
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.truncate_if_oversized",
                return_value=_VALID_EVENT,
            ),
        ):
            # Act
            uc(_VALID_EVENT)

        # Assert
        assert stats.events_sent == 1
        assert stats.invalid_events == 0
        assert stats.oversized == 0
        assert stats.dropped_buffer_full == 0
        assert stats.sidecar_dead == 0
        assert stats.internal_errors == 0
        transport.send.assert_called_once()


# ---------------------------------------------------------------------------
# Validation gate
# ---------------------------------------------------------------------------


class TestSendValidationFirst:
    def test_send_validates_first(self):
        """
        Given an event dict that fails validation,
        When SendEventUseCase is called,
        Then stats.invalid_events is incremented and transport.send is NOT called.
        """
        # Arrange
        uc, transport, codec, stats = _make_uc()

        with patch(
            "snitchbot.client.app.use_cases.send_event_uc.validate",
            return_value=["bad_version:2"],
        ):
            # Act
            uc({"v": 2})

        # Assert
        assert stats.invalid_events == 1
        assert stats.events_sent == 0
        transport.send.assert_not_called()

    def test_send_invalid_does_not_call_truncate(self):
        """
        Given an invalid event,
        When SendEventUseCase is called,
        Then truncate_if_oversized is NOT called (short-circuit after validation).
        """
        # Arrange
        uc, transport, codec, stats = _make_uc()

        with (
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.validate",
                return_value=["bad_version:missing"],
            ),
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.truncate_if_oversized",
            ) as mock_trunc,
        ):
            # Act
            uc({})

        # Assert
        mock_trunc.assert_not_called()


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


class TestSendTruncation:
    def test_send_truncates_oversized_then_sends(self):
        """
        Given an oversized event where truncation succeeds (returns a new dict),
        When SendEventUseCase is called,
        Then the truncated dict is packed and sent, stats.events_sent == 1.
        """
        # Arrange
        truncated = {**_VALID_EVENT, "payload": {"message": "x"}}
        uc, transport, codec, stats = _make_uc()

        with (
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.validate",
                return_value=[],
            ),
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.truncate_if_oversized",
                return_value=truncated,
            ),
        ):
            # Act
            uc(_VALID_EVENT)

        # Assert
        assert stats.events_sent == 1
        assert stats.oversized == 0
        # codec.pack was called with the truncated dict
        codec.pack.assert_called_once_with(truncated)

    def test_send_drops_still_oversized_increments_stats(self):
        """
        Given an event where truncation returns None (still oversized after all steps),
        When SendEventUseCase is called,
        Then stats.oversized is incremented and transport.send is NOT called.
        """
        # Arrange
        uc, transport, codec, stats = _make_uc()

        with (
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.validate",
                return_value=[],
            ),
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.truncate_if_oversized",
                return_value=None,
            ),
        ):
            # Act
            uc(_VALID_EVENT)

        # Assert
        assert stats.oversized == 1
        assert stats.events_sent == 0
        transport.send.assert_not_called()


# ---------------------------------------------------------------------------
# Transport errors
# ---------------------------------------------------------------------------


class TestSendTransportErrors:
    def test_send_buffer_full_increments_dropped(self):
        """
        Given transport.send raises TransportError("Buffer full"),
        When SendEventUseCase is called,
        Then stats.dropped_buffer_full is incremented, events_sent stays 0.
        """
        # Arrange
        transport = MagicMock()
        transport.send.side_effect = BufferFullError("Buffer full (EAGAIN)")
        uc, _, codec, stats = _make_uc(transport=transport)

        with (
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.validate",
                return_value=[],
            ),
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.truncate_if_oversized",
                return_value=_VALID_EVENT,
            ),
        ):
            # Act
            uc(_VALID_EVENT)

        # Assert
        assert stats.dropped_buffer_full == 1
        assert stats.events_sent == 0
        assert stats.sidecar_dead == 0

    def test_send_broken_pipe_increments_sidecar_dead(self):
        """
        Given transport.send raises TransportError("Sidecar dead"),
        When SendEventUseCase is called,
        Then stats.sidecar_dead is incremented, events_sent stays 0.
        """
        # Arrange
        transport = MagicMock()
        transport.send.side_effect = SidecarDeadError("Sidecar dead (BrokenPipe)")
        uc, _, codec, stats = _make_uc(transport=transport)

        with (
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.validate",
                return_value=[],
            ),
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.truncate_if_oversized",
                return_value=_VALID_EVENT,
            ),
        ):
            # Act
            uc(_VALID_EVENT)

        # Assert
        assert stats.sidecar_dead == 1
        assert stats.events_sent == 0
        assert stats.dropped_buffer_full == 0

    def test_send_other_transport_error_increments_internal_errors(self):
        """
        Given transport.send raises TransportError with an unrecognised message,
        When SendEventUseCase is called,
        Then stats.internal_errors is incremented.
        """
        # Arrange
        transport = MagicMock()
        transport.send.side_effect = TransportError("Send failed: some OS error")
        uc, _, codec, stats = _make_uc(transport=transport)

        with (
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.validate",
                return_value=[],
            ),
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.truncate_if_oversized",
                return_value=_VALID_EVENT,
            ),
        ):
            # Act
            uc(_VALID_EVENT)

        # Assert
        assert stats.internal_errors == 1
        assert stats.events_sent == 0


# ---------------------------------------------------------------------------
# P1 — never raises to caller
# ---------------------------------------------------------------------------


class TestSendNeverRaises:
    def test_send_never_raises_to_caller(self):
        """
        Given any unexpected exception raised inside the pipeline (e.g. from codec.pack),
        When SendEventUseCase is called,
        Then nothing propagates — stats.internal_errors is incremented (P1, I9).
        """
        # Arrange
        codec = MagicMock()
        codec.pack.side_effect = RuntimeError("unexpected codec failure")
        codec.size_of.return_value = 10
        uc, transport, _, stats = _make_uc(codec=codec)

        with (
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.validate",
                return_value=[],
            ),
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.truncate_if_oversized",
                return_value=_VALID_EVENT,
            ),
        ):
            # Act — must not raise
            uc(_VALID_EVENT)

        # Assert
        assert stats.internal_errors == 1
        assert stats.events_sent == 0

    def test_send_never_raises_when_validate_throws(self):
        """
        Given validate itself raises an unexpected exception,
        When SendEventUseCase is called,
        Then nothing propagates — stats.internal_errors is incremented.
        """
        # Arrange
        uc, transport, _, stats = _make_uc()

        with patch(
            "snitchbot.client.app.use_cases.send_event_uc.validate",
            side_effect=RuntimeError("validate exploded"),
        ):
            # Act — must not raise
            uc(_VALID_EVENT)

        # Assert
        assert stats.internal_errors == 1
        transport.send.assert_not_called()


# ---------------------------------------------------------------------------
# P5 — non-blocking (transport.send is called, not skipped)
# ---------------------------------------------------------------------------


class TestSendNonBlocking:
    def test_send_non_blocking_transport_send_called(self):
        """
        Given a valid event,
        When SendEventUseCase is called,
        Then transport.send is invoked exactly once with the packed bytes (P5).
        """
        # Arrange
        packed = b"\x82\xa1v\x01"
        codec = MagicMock()
        codec.pack.return_value = packed
        codec.size_of.return_value = 10
        uc, transport, _, stats = _make_uc(codec=codec)

        with (
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.validate",
                return_value=[],
            ),
            patch(
                "snitchbot.client.app.use_cases.send_event_uc.truncate_if_oversized",
                return_value=_VALID_EVENT,
            ),
        ):
            # Act
            uc(_VALID_EVENT)

        # Assert
        transport.send.assert_called_once_with(packed)
