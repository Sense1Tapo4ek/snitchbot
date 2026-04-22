"""Unit tests for SnitchbotLoggingHandler.

Spec: docs/superpowers/specs/2026-04-11-logging-integration-design.md §3-§8.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 13.1.
Invariants: L1, L2, L3, L4, L5, L6, L7, L8, L9, L10.
"""
import logging
import threading
import time
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    msg: str = "test message",
    level: int = logging.WARNING,
    exc_info: object = None,
    extra_attrs: dict | None = None,
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=level,
        pathname="/app/orders.py",
        lineno=42,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    record.funcName = "create_order"
    if extra_attrs:
        for k, v in extra_attrs.items():
            setattr(record, k, v)
    return record


# ---------------------------------------------------------------------------
# Tests: class shape and constructor
# ---------------------------------------------------------------------------


class TestHandlerIsSubclassOfLoggingHandler:
    def test_handler_is_subclass_of_logging_Handler(self) -> None:
        """
        Given SnitchbotLoggingHandler,
        When checked for inheritance,
        Then it is a subclass of logging.Handler (L2 — plugs into stdlib logging).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        assert issubclass(SnitchbotLoggingHandler, logging.Handler)

    def test_handler_instantiation_with_callable(self) -> None:
        """
        Given a callable send_event,
        When constructing SnitchbotLoggingHandler(send_event),
        Then it creates without error.
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        handler = SnitchbotLoggingHandler(send_event=MagicMock())
        assert handler is not None


class TestDefaultLevel:
    def test_handler_default_level_WARNING(self) -> None:
        """
        Given SnitchbotLoggingHandler with no explicit level,
        When checking its level,
        Then it is logging.WARNING (L3/L4).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        handler = SnitchbotLoggingHandler(send_event=MagicMock())
        assert handler.level == logging.WARNING

    def test_handler_level_below_WARNING_clamped_to_WARNING(self) -> None:
        """
        Given SnitchbotLoggingHandler constructed with level=logging.DEBUG,
        When checking the effective level,
        Then it is WARNING, not DEBUG (L3, L4 — cannot lower below WARNING).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        handler = SnitchbotLoggingHandler(send_event=MagicMock(), level=logging.DEBUG)
        assert handler.level == logging.WARNING

    def test_handler_level_INFO_clamped_to_WARNING(self) -> None:
        """
        Given SnitchbotLoggingHandler constructed with level=logging.INFO,
        When checking the effective level,
        Then it is WARNING (L4 clamp).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        handler = SnitchbotLoggingHandler(send_event=MagicMock(), level=logging.INFO)
        assert handler.level == logging.WARNING

    def test_handler_level_ERROR_stays_ERROR(self) -> None:
        """
        Given SnitchbotLoggingHandler constructed with level=logging.ERROR,
        When checking the level,
        Then it is ERROR (L4: can tighten above WARNING).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        handler = SnitchbotLoggingHandler(send_event=MagicMock(), level=logging.ERROR)
        assert handler.level == logging.ERROR


# ---------------------------------------------------------------------------
# Tests: filtering — what gets forwarded
# ---------------------------------------------------------------------------


class TestForwardingFilter:
    def test_debug_info_never_forwarded(self) -> None:
        """
        Given a WARNING-level handler,
        When records at DEBUG and INFO are emitted,
        Then send_event is never called (L3).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        send_event = MagicMock()
        handler = SnitchbotLoggingHandler(send_event=send_event)

        handler.emit(_make_record(level=logging.DEBUG))
        handler.emit(_make_record(level=logging.INFO))

        send_event.assert_not_called()

    def test_warning_record_forwarded(self) -> None:
        """
        Given a WARNING-level handler,
        When a WARNING record is emitted,
        Then send_event is called once (L6).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        send_event = MagicMock()
        handler = SnitchbotLoggingHandler(send_event=send_event)

        handler.emit(_make_record(level=logging.WARNING))

        send_event.assert_called_once()

    def test_handler_level_ERROR_filters_out_warnings(self) -> None:
        """
        Given a handler constructed with level=ERROR,
        When a WARNING record is emitted,
        Then send_event is not called (L4: stricter filter is honoured).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        send_event = MagicMock()
        handler = SnitchbotLoggingHandler(send_event=send_event, level=logging.ERROR)

        handler.emit(_make_record(level=logging.WARNING))

        send_event.assert_not_called()

    def test_error_and_critical_forwarded(self) -> None:
        """
        Given a WARNING-level handler,
        When ERROR and CRITICAL records are emitted,
        Then send_event is called for each (L3 — only DEBUG/INFO are blocked).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        send_event = MagicMock()
        handler = SnitchbotLoggingHandler(send_event=send_event)

        handler.emit(_make_record(level=logging.ERROR))
        handler.emit(_make_record(level=logging.CRITICAL))

        assert send_event.call_count == 2


# ---------------------------------------------------------------------------
# Tests: payload construction
# ---------------------------------------------------------------------------


class TestPayloadConstruction:
    def test_warning_record_builds_custom_event_source_logging(self) -> None:
        """
        Given a WARNING LogRecord,
        When SnitchbotLoggingHandler.emit() is called,
        Then send_event receives a dict with source='logging' (L6).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        send_event = MagicMock()
        handler = SnitchbotLoggingHandler(send_event=send_event)

        handler.emit(_make_record(msg="something bad happened", level=logging.WARNING))

        args, kwargs = send_event.call_args
        payload = args[0] if args else kwargs
        assert payload.get("source") == "logging"

    def test_caller_file_line_func_from_record(self) -> None:
        """
        Given a LogRecord with pathname, lineno, funcName,
        When emit() is called,
        Then send_event receives caller dict with file, line, func (L6, §5.1).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        send_event = MagicMock()
        handler = SnitchbotLoggingHandler(send_event=send_event)

        record = _make_record(level=logging.ERROR)
        record.pathname = "/app/payments.py"
        record.lineno = 99
        record.funcName = "process_payment"
        handler.emit(record)

        args, kwargs = send_event.call_args
        payload = args[0] if args else kwargs
        caller = payload.get("caller") or {}
        assert caller.get("file") == "/app/payments.py"
        assert caller.get("line") == 99
        assert caller.get("func") == "process_payment"

    def test_extras_extracted_from_record_excluding_standard_attrs(self) -> None:
        """
        Given a LogRecord with user-supplied extra attributes,
        When emit() is called,
        Then send_event receives extras containing only non-standard attrs (L6, §5.1).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        send_event = MagicMock()
        handler = SnitchbotLoggingHandler(send_event=send_event)

        record = _make_record(level=logging.WARNING, extra_attrs={"user_id": 42, "order_id": "abc"})
        handler.emit(record)

        args, kwargs = send_event.call_args
        payload = args[0] if args else kwargs
        extras = payload.get("extras") or {}
        assert extras.get("user_id") == 42
        assert extras.get("order_id") == "abc"
        # Standard attrs must not be in extras
        assert "levelno" not in extras
        assert "pathname" not in extras
        assert "funcName" not in extras

    def test_log_exception_includes_exc_info_in_payload(self) -> None:
        """
        Given a LogRecord with exc_info (simulating log.exception(...)),
        When emit() is called,
        Then send_event payload contains non-None exception field (L6, §5.1).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        send_event = MagicMock()
        handler = SnitchbotLoggingHandler(send_event=send_event)

        try:
            raise ValueError("something broke")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = _make_record(level=logging.ERROR, exc_info=exc_info)
        handler.emit(record)

        args, kwargs = send_event.call_args
        payload = args[0] if args else kwargs
        # _exc_value field should be present and non-None (BaseException object)
        assert payload.get("_exc_value") is not None
        assert isinstance(payload["_exc_value"], ValueError)


# ---------------------------------------------------------------------------
# Tests: error handling and resilience
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_handler_exception_swallowed_never_raises(self) -> None:
        """
        Given a send_event callable that raises an exception,
        When emit() is called,
        Then the exception is swallowed and not propagated to the caller (L1).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        def boom(_payload: dict) -> None:
            raise RuntimeError("send failed")

        handler = SnitchbotLoggingHandler(send_event=boom)
        record = _make_record(level=logging.WARNING)

        # Must not raise
        handler.emit(record)

    def test_passthrough_existing_handlers_untouched(self) -> None:
        """
        Given a logger with an existing handler,
        When SnitchbotLoggingHandler is added and a record is emitted,
        Then the existing handler still receives the record (L2 — additive only).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        existing_handler = MagicMock(spec=logging.Handler)
        existing_handler.level = logging.NOTSET
        existing_handler.handle = MagicMock()

        logger = logging.getLogger("test.passthrough." + str(id(existing_handler)))
        logger.addHandler(existing_handler)
        logger.addHandler(SnitchbotLoggingHandler(send_event=MagicMock()))
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        try:
            logger.warning("hello")
        finally:
            logger.handlers.clear()

        existing_handler.handle.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: recursion guard
# ---------------------------------------------------------------------------


class TestRecursionGuard:
    def test_recursion_protection_via_thread_local_active_flag(self) -> None:
        """
        Given a send_event that itself triggers another emit on the same handler,
        When emit() is called,
        Then recursion is detected and the inner call is dropped — no infinite loop (L5).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        call_count = 0

        def recursive_send(_payload: dict) -> None:
            nonlocal call_count
            call_count += 1
            # Simulate re-entrant logging via the handler
            handler.emit(_make_record(level=logging.WARNING, msg="inner"))

        handler = SnitchbotLoggingHandler(send_event=recursive_send)
        handler.emit(_make_record(level=logging.WARNING, msg="outer"))

        # Only the outer call should produce one send_event invocation
        assert call_count == 1


# ---------------------------------------------------------------------------
# Tests: disabled mode and import isolation
# ---------------------------------------------------------------------------


class TestDisabledMode:
    def test_disabled_mode_zero_forward_no_cost(self) -> None:
        """
        Given SnitchbotLoggingHandler with send_event that checks a disabled flag,
        When disabled=True and a WARNING record is emitted,
        Then send_event is not called (L9 — zero cost in disabled mode).
        """
        from snitchbot.integrations.logging_handler import SnitchbotLoggingHandler

        send_event = MagicMock()
        handler = SnitchbotLoggingHandler(send_event=send_event, disabled=True)

        handler.emit(_make_record(level=logging.WARNING))
        handler.emit(_make_record(level=logging.ERROR))
        handler.emit(_make_record(level=logging.CRITICAL))

        send_event.assert_not_called()


class TestImportIsolation:
    def test_not_auto_imported_with_mylib_base(self) -> None:
        """
        Given a fresh import of mylib,
        When checking the top-level namespace,
        Then SnitchbotLoggingHandler is NOT present — it lives in mylib.integrations (L10).
        """
        import snitchbot

        assert not hasattr(snitchbot, "SnitchbotLoggingHandler"), (
            "SnitchbotLoggingHandler should not be auto-imported into mylib top-level (L10)"
        )
        assert not hasattr(snitchbot, "LoggingHandler"), (
            "LoggingHandler should not be auto-imported into mylib top-level (L10)"
        )
