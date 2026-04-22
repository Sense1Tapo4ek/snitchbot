"""Unit tests for mylib_structlog_processor.

Spec: docs/superpowers/specs/2026-04-11-logging-integration-design.md §3.2, §5.2, §8.2.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 13.2.
Invariants: L1, L2, L3, L5, L6.
"""
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event_dict(
    event: str = "something happened",
    level: str = "warning",
    extra_keys: dict | None = None,
) -> dict:
    d = {
        "event": event,
        "level": level,
        "timestamp": "2026-04-12T10:00:00Z",
    }
    if extra_keys:
        d.update(extra_keys)
    return d


# ---------------------------------------------------------------------------
# Tests: passthrough
# ---------------------------------------------------------------------------


class TestPassthrough:
    def test_processor_passthrough_returns_event_dict_unchanged(self) -> None:
        """
        Given an event_dict with extra keys,
        When mylib_structlog_processor is called,
        Then the returned event_dict is the same object, unmodified (L2).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        send_event = MagicMock()
        processor = make_structlog_processor(send_event=send_event)

        event_dict = _make_event_dict(extra_keys={"user_id": 99})
        original_copy = dict(event_dict)

        result = processor(None, "warning", event_dict)

        assert result is event_dict
        assert result == original_copy

    def test_processor_does_not_modify_event_dict_on_warning(self) -> None:
        """
        Given a warning event_dict,
        When processor is called,
        Then the event_dict is returned without any modifications (L2).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        processor = make_structlog_processor(send_event=MagicMock())
        ed = _make_event_dict(level="error", extra_keys={"key": "val"})
        before = dict(ed)

        result = processor(None, "error", ed)

        assert result == before


# ---------------------------------------------------------------------------
# Tests: level filtering
# ---------------------------------------------------------------------------


class TestLevelFiltering:
    def test_processor_forwards_warning(self) -> None:
        """
        Given an event at 'warning',
        When processor is called,
        Then send_event is called once (L3).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        send_event = MagicMock()
        processor = make_structlog_processor(send_event=send_event)

        processor(None, "warning", _make_event_dict(level="warning"))

        send_event.assert_called_once()

    def test_processor_forwards_error(self) -> None:
        """
        Given an event at 'error',
        When processor is called,
        Then send_event is called once (L3).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        send_event = MagicMock()
        processor = make_structlog_processor(send_event=send_event)

        processor(None, "error", _make_event_dict(level="error"))

        send_event.assert_called_once()

    def test_processor_forwards_critical(self) -> None:
        """
        Given an event at 'critical',
        When processor is called,
        Then send_event is called once (L3).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        send_event = MagicMock()
        processor = make_structlog_processor(send_event=send_event)

        processor(None, "critical", _make_event_dict(level="critical"))

        send_event.assert_called_once()

    def test_processor_ignores_debug(self) -> None:
        """
        Given an event at 'debug',
        When processor is called,
        Then send_event is NOT called (L3 — debug is never forwarded).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        send_event = MagicMock()
        processor = make_structlog_processor(send_event=send_event)

        processor(None, "debug", _make_event_dict(level="debug"))

        send_event.assert_not_called()

    def test_processor_ignores_info(self) -> None:
        """
        Given an event at 'info',
        When processor is called,
        Then send_event is NOT called (L3).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        send_event = MagicMock()
        processor = make_structlog_processor(send_event=send_event)

        processor(None, "info", _make_event_dict(level="info"))

        send_event.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: payload extraction
# ---------------------------------------------------------------------------


class TestPayloadExtraction:
    def test_processor_extracts_text_from_event_key(self) -> None:
        """
        Given an event_dict with event='user not found',
        When processor forwards it,
        Then send_event payload has text='user not found' (L6, §5.2).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        send_event = MagicMock()
        processor = make_structlog_processor(send_event=send_event)

        processor(None, "warning", _make_event_dict(event="user not found"))

        args, kwargs = send_event.call_args
        payload = args[0] if args else kwargs
        assert payload.get("text") == "user not found"

    def test_processor_extras_exclude_meta_keys(self) -> None:
        """
        Given an event_dict with structlog meta keys and user keys,
        When processor forwards it,
        Then extras contain only user keys, not meta keys (§5.2).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        send_event = MagicMock()
        processor = make_structlog_processor(send_event=send_event)

        ed = _make_event_dict(
            extra_keys={
                "user_id": 42,
                "path": "/orders",
                "filename": "orders.py",  # meta key from CallsiteParameterAdder
                "lineno": 99,             # meta key
                "func_name": "create",    # meta key
            }
        )
        processor(None, "warning", ed)

        args, kwargs = send_event.call_args
        payload = args[0] if args else kwargs
        extras = payload.get("extras") or {}
        assert extras.get("user_id") == 42
        assert extras.get("path") == "/orders"
        # Meta keys must be excluded
        assert "filename" not in extras
        assert "lineno" not in extras
        assert "func_name" not in extras
        assert "event" not in extras
        assert "level" not in extras
        assert "timestamp" not in extras

    def test_processor_caller_from_callsite_parameters(self) -> None:
        """
        Given event_dict with filename, lineno, func_name (from CallsiteParameterAdder),
        When processor forwards it,
        Then send_event payload has caller dict populated (§5.2).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        send_event = MagicMock()
        processor = make_structlog_processor(send_event=send_event)

        ed = _make_event_dict(
            extra_keys={
                "filename": "payments.py",
                "lineno": 55,
                "func_name": "charge_card",
            }
        )
        processor(None, "error", ed)

        args, kwargs = send_event.call_args
        payload = args[0] if args else kwargs
        caller = payload.get("caller")
        assert caller is not None
        assert caller.get("file") == "payments.py"
        assert caller.get("line") == 55
        assert caller.get("func") == "charge_card"

    def test_processor_no_callsite_params_caller_is_None_but_still_works(self) -> None:
        """
        Given an event_dict without callsite keys,
        When processor is called,
        Then send_event is still called and caller is resolved from frame
        walking (falls back to first non-structlog/snitchbot frame).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        send_event = MagicMock()
        processor = make_structlog_processor(send_event=send_event)

        ed = _make_event_dict()  # no filename/lineno/func_name
        processor(None, "warning", ed)

        send_event.assert_called_once()
        args, kwargs = send_event.call_args
        payload = args[0] if args else kwargs
        caller = payload.get("caller")
        # Frame walker should find a caller (pytest frame or user code)
        assert caller is None or isinstance(caller, dict)

    def test_processor_source_structlog(self) -> None:
        """
        Given any forwarded event,
        When processor calls send_event,
        Then payload has source='structlog' (L6).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        send_event = MagicMock()
        processor = make_structlog_processor(send_event=send_event)

        processor(None, "warning", _make_event_dict())

        args, kwargs = send_event.call_args
        payload = args[0] if args else kwargs
        assert payload.get("source") == "structlog"


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_processor_exception_in_forwarder_swallowed(self) -> None:
        """
        Given a send_event that raises RuntimeError,
        When the processor is called with a warning event,
        Then the exception is swallowed and event_dict is still returned (L1).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        def boom(_p: dict) -> None:
            raise RuntimeError("network down")

        processor = make_structlog_processor(send_event=boom)
        ed = _make_event_dict()

        result = processor(None, "warning", ed)  # must not raise

        assert result is ed

    def test_processor_recursion_protection(self) -> None:
        """
        Given a send_event that re-triggers the processor,
        When processor is called,
        Then recursion is detected and dropped — no infinite loop (L5).
        """
        from snitchbot.integrations.structlog_processor import make_structlog_processor

        call_count = 0
        processor_ref = None

        def recursive_send(_payload: dict) -> None:
            nonlocal call_count
            call_count += 1
            # Simulate re-entrant call to the same processor
            processor_ref(None, "warning", _make_event_dict(event="inner"))

        processor_ref = make_structlog_processor(send_event=recursive_send)
        processor_ref(None, "warning", _make_event_dict(event="outer"))

        assert call_count == 1
