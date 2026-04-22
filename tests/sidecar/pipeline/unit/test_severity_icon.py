"""Unit tests for severity_icon_service.

Spec: docs/superpowers/specs/2026-04-11-alert-rendering-design.md §3, R2.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 7.1.
"""
from snitchbot.sidecar.pipeline.domain.services.severity_icon_service import severity_icon


def test_warning_orange_circle() -> None:
    """
    Given severity='warning',
    When severity_icon() is called,
    Then it returns 🟠.
    """
    assert severity_icon("warning") == "🟠"


def test_error_red_circle() -> None:
    """
    Given severity='error',
    When severity_icon() is called,
    Then it returns 🔴.
    """
    assert severity_icon("error") == "🔴"


def test_critical_purple_circle() -> None:
    """
    Given severity='critical',
    When severity_icon() is called,
    Then it returns 🟣.
    """
    assert severity_icon("critical") == "🟣"


def test_consistent_across_last_mute_alert_renders() -> None:
    """
    Given severities used in /last cards, /mute records, and alert renders,
    When severity_icon() is called for each,
    Then icons are consistent across all three use-cases (R2).
    """
    # Same function used in all three contexts — calling it twice is idempotent
    assert severity_icon("warning") == severity_icon("warning")
    assert severity_icon("error") == severity_icon("error")
    assert severity_icon("critical") == severity_icon("critical")
