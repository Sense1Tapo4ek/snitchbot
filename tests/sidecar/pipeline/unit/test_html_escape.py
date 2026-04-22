"""Unit tests for html_escape_service.

Spec: docs/superpowers/specs/2026-04-11-alert-rendering-design.md §9, R11.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 7.2.
"""
from snitchbot.sidecar.pipeline.domain.services.html_escape_service import escape_html


def test_escape_ampersand_lt_gt() -> None:
    """
    Given a string containing &, <, >,
    When escape_html() is called,
    Then they are replaced with &amp;, &lt;, &gt; respectively (R11).
    """
    assert escape_html("a & b") == "a &amp; b"
    assert escape_html("a < b") == "a &lt; b"
    assert escape_html("a > b") == "a &gt; b"
    assert escape_html("<script>alert('xss')</script>") == "&lt;script&gt;alert('xss')&lt;/script&gt;"


def test_escape_applied_to_user_supplied_values() -> None:
    """
    Given user-supplied text with HTML special characters,
    When escape_html() is called,
    Then the result is safe for embedding in Telegram HTML parse_mode (R11).
    """
    raw = "Error: connection refused to 10.0.0.5:5432 & timeout > 30s"
    escaped = escape_html(raw)
    assert "&" not in escaped or "&amp;" in escaped
    assert "<" not in escaped
    assert ">" not in escaped
    assert "10.0.0.5:5432" in escaped


def test_does_not_escape_template_literals() -> None:
    """
    Given plain text with no HTML special characters,
    When escape_html() is called,
    Then the string is returned unchanged.
    """
    plain = "orders-api pid 101 MainThread"
    assert escape_html(plain) == plain
