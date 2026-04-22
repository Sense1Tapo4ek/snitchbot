"""Unit tests for WatchdogPolicyService — severity escalation logic.

CI14: first hit in window -> 'warning'; repeated hit within 60 s -> 'error'.
No mocks: pure domain, uses real objects only.
"""
import time

import pytest

from snitchbot.client.domain.services.watchdog_policy_service import WatchdogPolicyService


class TestWatchdogPolicySeverity:
    def test_first_hit_severity_warning(self):
        """
        Given a fresh policy (no prior hits),
        When compute_severity is called,
        Then it returns 'warning' and records the window start.
        """
        # Arrange
        policy = WatchdogPolicyService(escalation_window_sec=60)
        now = time.monotonic()

        # Act
        severity = policy.compute_severity(now)

        # Assert
        assert severity == "warning"

    def test_second_hit_within_60s_severity_error(self):
        """
        Given a policy that already fired a warning,
        When compute_severity is called again within 60 s,
        Then it returns 'error' (CI14: escalation within window).
        """
        # Arrange
        policy = WatchdogPolicyService(escalation_window_sec=60)
        now = time.monotonic()

        # Act
        first = policy.compute_severity(now)
        second = policy.compute_severity(now + 5.0)  # 5 s later — within window

        # Assert
        assert first == "warning"
        assert second == "error"

    def test_hit_after_60s_window_resets_to_warning(self):
        """
        Given a policy that fired a warning,
        When compute_severity is called after the escalation window expires,
        Then it resets and returns 'warning' again.
        """
        # Arrange
        policy = WatchdogPolicyService(escalation_window_sec=60)
        now = time.monotonic()

        # Act
        first = policy.compute_severity(now)
        after_window = policy.compute_severity(now + 61.0)  # beyond 60 s window

        # Assert
        assert first == "warning"
        assert after_window == "warning"

    def test_third_hit_within_window_still_error(self):
        """
        Given escalation already in effect,
        When a third hit arrives within the window,
        Then it stays 'error'.
        """
        # Arrange
        policy = WatchdogPolicyService(escalation_window_sec=60)
        now = time.monotonic()

        # Act
        policy.compute_severity(now)
        policy.compute_severity(now + 5.0)
        third = policy.compute_severity(now + 10.0)

        # Assert
        assert third == "error"

    def test_reset_after_window_then_escalates_again(self):
        """
        Given a full escalation -> reset -> second cycle,
        When hits arrive within the new window,
        Then the second cycle follows warning -> error pattern.
        """
        # Arrange
        policy = WatchdogPolicyService(escalation_window_sec=60)
        now = time.monotonic()

        # Act — first window
        policy.compute_severity(now)
        policy.compute_severity(now + 5.0)

        # Act — after window reset
        reset_now = now + 65.0
        after_reset = policy.compute_severity(reset_now)
        after_reset_second = policy.compute_severity(reset_now + 5.0)

        # Assert
        assert after_reset == "warning"
        assert after_reset_second == "error"

    def test_custom_escalation_window(self):
        """
        Given a policy with a short escalation window (5 s),
        When hits arrive at 0 s and 6 s,
        Then the second hit is 'warning' (window expired).
        """
        # Arrange
        policy = WatchdogPolicyService(escalation_window_sec=5)
        now = time.monotonic()

        # Act
        policy.compute_severity(now)
        second = policy.compute_severity(now + 6.0)

        # Assert
        assert second == "warning"


# ---------------------------------------------------------------------------
# Multi-threshold severity (v2)
# ---------------------------------------------------------------------------


class TestMultiThresholdSeverity:
    def test_block_below_error_threshold_returns_warning(self):
        """
        Given error_threshold_ms=2000,
        When block_ms=1500 (below error threshold),
        Then severity is 'warning'.
        """
        policy = WatchdogPolicyService(
            escalation_window_sec=60,
            error_threshold_ms=2000,
            critical_threshold_ms=5000,
        )
        now = time.monotonic()
        severity = policy.compute_severity(now, block_ms=1500.0)
        assert severity == "warning"

    def test_block_above_error_threshold_returns_error(self):
        """
        Given error_threshold_ms=2000,
        When block_ms=2500 (above error, below critical),
        Then severity is 'error'.
        """
        policy = WatchdogPolicyService(
            escalation_window_sec=60,
            error_threshold_ms=2000,
            critical_threshold_ms=5000,
        )
        now = time.monotonic()
        severity = policy.compute_severity(now, block_ms=2500.0)
        assert severity == "error"

    def test_block_above_critical_threshold_returns_critical(self):
        """
        Given critical_threshold_ms=5000,
        When block_ms=6000,
        Then severity is 'critical'.
        """
        policy = WatchdogPolicyService(
            escalation_window_sec=60,
            error_threshold_ms=2000,
            critical_threshold_ms=5000,
        )
        now = time.monotonic()
        severity = policy.compute_severity(now, block_ms=6000.0)
        assert severity == "critical"

    def test_escalation_bumps_warning_to_error_within_window(self):
        """
        Given two warning-level blocks within escalation window,
        When compute_severity is called,
        Then second hit escalates from warning to error.
        """
        policy = WatchdogPolicyService(
            escalation_window_sec=60,
            error_threshold_ms=2000,
            critical_threshold_ms=5000,
        )
        now = time.monotonic()
        first = policy.compute_severity(now, block_ms=800.0)
        second = policy.compute_severity(now + 5.0, block_ms=800.0)
        assert first == "warning"
        assert second == "error"

    def test_escalation_bumps_error_to_critical_within_window(self):
        """
        Given first hit is error-level, second within window,
        When compute_severity is called,
        Then second escalates from error to critical.
        """
        policy = WatchdogPolicyService(
            escalation_window_sec=60,
            error_threshold_ms=2000,
            critical_threshold_ms=5000,
        )
        now = time.monotonic()
        first = policy.compute_severity(now, block_ms=3000.0)
        second = policy.compute_severity(now + 5.0, block_ms=3000.0)
        assert first == "error"
        assert second == "critical"

    def test_critical_stays_critical_on_escalation(self):
        """
        Given block_ms already at critical level,
        When escalation tries to bump above critical,
        Then severity stays 'critical' (capped).
        """
        policy = WatchdogPolicyService(
            escalation_window_sec=60,
            error_threshold_ms=2000,
            critical_threshold_ms=5000,
        )
        now = time.monotonic()
        first = policy.compute_severity(now, block_ms=6000.0)
        second = policy.compute_severity(now + 5.0, block_ms=6000.0)
        assert first == "critical"
        assert second == "critical"

    def test_no_thresholds_falls_back_to_warning_error_pattern(self):
        """
        Given no error/critical thresholds (v1 backward compat),
        When hits arrive,
        Then warning -> error escalation still works.
        """
        policy = WatchdogPolicyService(
            escalation_window_sec=60,
            error_threshold_ms=None,
            critical_threshold_ms=None,
        )
        now = time.monotonic()
        first = policy.compute_severity(now, block_ms=800.0)
        second = policy.compute_severity(now + 5.0, block_ms=800.0)
        assert first == "warning"
        assert second == "error"
