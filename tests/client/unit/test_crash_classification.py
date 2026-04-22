"""Unit tests for crash classification service — Task 4.1.

Spec: docs/superpowers/specs/2026-04-11-client-internals-design.md §3.6
      docs/superpowers/specs/2026-04-11-event-model-design.md §5
Invariants covered: CI7 (KeyboardInterrupt is error, not critical)
"""
import pytest

from snitchbot.client.domain.services.crash_classification_service import (
    classify_crash_severity,
)


class TestCrashClassificationCritical:
    def test_memory_error_is_critical(self):
        """
        Given MemoryError,
        When classifying severity,
        Then 'critical' is returned.
        """
        assert classify_crash_severity(MemoryError) == "critical"

    def test_system_exit_is_critical(self):
        """
        Given SystemExit,
        When classifying severity,
        Then 'critical' is returned.
        """
        assert classify_crash_severity(SystemExit) == "critical"

    def test_deep_subclass_of_memory_error_is_critical(self):
        """
        Given a subclass of MemoryError,
        When classifying severity,
        Then 'critical' is returned (subclass check via issubclass).
        """

        class MyOOM(MemoryError):
            pass

        assert classify_crash_severity(MyOOM) == "critical"


class TestCrashClassificationError:
    def test_value_error_is_error(self):
        """
        Given ValueError,
        When classifying severity,
        Then 'error' is returned.
        """
        assert classify_crash_severity(ValueError) == "error"

    def test_keyboard_interrupt_is_error_not_critical(self):
        """
        Given KeyboardInterrupt (CI7 — handled by SIGINT path, not crash critical),
        When classifying severity,
        Then 'error' is returned (not 'critical').
        """
        assert classify_crash_severity(KeyboardInterrupt) == "error"

    def test_runtime_error_is_error(self):
        """
        Given RuntimeError,
        When classifying severity,
        Then 'error' is returned.
        """
        assert classify_crash_severity(RuntimeError) == "error"

    def test_base_exception_is_error(self):
        """
        Given BaseException (root of hierarchy),
        When classifying severity,
        Then 'error' is returned.
        """
        assert classify_crash_severity(BaseException) == "error"
