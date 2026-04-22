"""Unit tests for lifecycle_render_service.

Spec: docs/superpowers/specs/2026-04-11-alert-rendering-design.md §5, R5.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 7.4.
"""
from snitchbot.sidecar.pipeline.domain.services.lifecycle_render_service import render_lifecycle

_SERVICE = "orders-api"


def _startup_event(pid: int = 101) -> dict:
    return {
        "kind": "lifecycle",
        "severity": None,
        "pid": pid,
        "ts": 1744377730.0,
        "fingerprint": None,
        "context": None,
        "payload": {
            "phase": "startup",
            "reason": "init",
            "exit_code": None,
        },
    }


def _shutdown_graceful_event(pid: int = 101) -> dict:
    return {
        "kind": "lifecycle",
        "severity": None,
        "pid": pid,
        "ts": 1744377730.0,
        "fingerprint": None,
        "context": None,
        "payload": {
            "phase": "shutdown",
            "reason": "sigterm",
            "exit_code": 0,
        },
    }


def _shutdown_crash_event(pid: int = 101) -> dict:
    return {
        "kind": "lifecycle",
        "severity": None,
        "pid": pid,
        "ts": 1744377730.0,
        "fingerprint": None,
        "context": None,
        "payload": {
            "phase": "shutdown",
            "reason": "crash",
            "exit_code": None,
        },
    }


def test_startup_format_triangle_right() -> None:
    """
    Given a startup lifecycle event,
    When render_lifecycle() is called,
    Then output starts with ▶ and contains 'started' and service name.
    """
    event = _startup_event()
    html = render_lifecycle(event=event, service=_SERVICE)

    assert "▶" in html
    assert "started" in html
    assert _SERVICE in html
    assert "pid" in html


def test_shutdown_graceful_format_square() -> None:
    """
    Given a graceful shutdown lifecycle event,
    When render_lifecycle() is called,
    Then output contains ■ (or ⏹) and 'stopped' and service name.
    """
    event = _shutdown_graceful_event()
    html = render_lifecycle(event=event, service=_SERVICE)

    # Spec uses ■ for graceful shutdown
    assert ("■" in html or "⏹" in html)
    assert "stopped" in html
    assert _SERVICE in html
    assert "sigterm" in html


def test_shutdown_crash_format_warning() -> None:
    """
    Given a crash shutdown lifecycle event,
    When render_lifecycle() is called,
    Then output contains ⚠ and 'crashed' and service name.
    """
    event = _shutdown_crash_event()
    html = render_lifecycle(event=event, service=_SERVICE)

    assert "⚠" in html
    assert "crashed" in html
    assert _SERVICE in html


def test_no_inline_buttons_on_lifecycle() -> None:
    """
    Given any lifecycle event,
    When render_lifecycle() is called,
    Then no mute or trace buttons appear in the output (R5).
    """
    for event in [_startup_event(), _shutdown_graceful_event(), _shutdown_crash_event()]:
        html = render_lifecycle(event=event, service=_SERVICE)
        assert "🔇" not in html
        assert "📋" not in html


def test_no_severity_icon_on_lifecycle() -> None:
    """
    Given any lifecycle event,
    When render_lifecycle() is called,
    Then no severity icons (🟠, 🔴, 🟣) appear in the output (R5).
    """
    for event in [_startup_event(), _shutdown_graceful_event(), _shutdown_crash_event()]:
        html = render_lifecycle(event=event, service=_SERVICE)
        assert "🟠" not in html
        assert "🔴" not in html
        assert "🟣" not in html


def test_no_counter_no_fingerprint_on_lifecycle() -> None:
    """
    Given any lifecycle event,
    When render_lifecycle() is called,
    Then no '×' counter and no fingerprint <code> block appear (R5).
    """
    for event in [_startup_event(), _shutdown_graceful_event(), _shutdown_crash_event()]:
        html = render_lifecycle(event=event, service=_SERVICE)
        assert "×" not in html
        # fingerprint would be wrapped in <code> as 6 hex chars; none expected
        assert "fingerprint" not in html.lower() or "<code>" not in html
