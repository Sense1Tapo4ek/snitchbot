"""Unit tests for scrub_render_service.

Spec: docs/superpowers/specs/2026-04-11-alert-rendering-design.md §9, R7.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 7.6.
Invariants: S1, S2, R7.
"""
import copy

from snitchbot.sidecar.pipeline.domain.services.scrub_render_service import scrub_and_render

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# A value that the generic-kv regex will redact when paired with 'api_key='
_SECRET_VALUE = "abc123xyz_secret"


def _make_crash_event(message: str = "db error") -> dict:
    return {
        "kind": "crash",
        "service": "orders-api",
        "context": {},
        "payload": {
            "message": message,
            "stack": [
                {
                    "file": "app/db.py",
                    "line": 10,
                    "func": "connect",
                    "code": "conn = db.connect()",
                    "is_user_code": True,
                },
            ],
        },
    }


def _make_custom_event(text: str = "notify text", extras: dict | None = None) -> dict:
    return {
        "kind": "custom",
        "service": "orders-api",
        "context": {"trace_id": "abc123"},
        "payload": {
            "text": text,
            "extras": extras or {},
        },
    }


def _simple_render(*, event: dict) -> str:
    """Minimal render function that concatenates all string values."""
    parts = []
    payload = event.get("payload", {})
    if isinstance(payload.get("message"), str):
        parts.append(payload["message"])
    if isinstance(payload.get("text"), str):
        parts.append(payload["text"])
    for frame in payload.get("stack", []):
        if isinstance(frame.get("code"), str):
            parts.append(frame["code"])
    for v in (payload.get("extras") or {}).values():
        if isinstance(v, str):
            parts.append(v)
    ctx = event.get("context") or {}
    for v in ctx.values():
        if isinstance(v, str):
            parts.append(v)
    return " | ".join(parts)


def _scrub_fn(event: dict) -> dict:
    from snitchbot.shared.domain.services.scrubbing_service import scrub_event
    return scrub_event(event)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestScrubAppliedBeforeRender:
    def test_scrub_applied_before_render(self) -> None:
        """
        Given an event whose message contains a secret pattern matched by generic-kv,
        When scrub_and_render() is called,
        Then the rendered output does NOT contain the raw secret (S1).
        """
        # api_key= triggers the generic-kv regex (api_key ends with 'key')
        event = _make_crash_event(message=f"api_key={_SECRET_VALUE}")
        result = scrub_and_render(event=event, render_fn=_simple_render, scrub_fn=_scrub_fn)
        assert _SECRET_VALUE not in result

    def test_scrub_applied_to_exception_message(self) -> None:
        """
        Given a crash event whose exception message contains a secret,
        When scrub_and_render() is called,
        Then the secret is removed from the rendered output (R7).
        """
        # db_password= triggers the generic-kv regex (db_password ends with 'password')
        secret = "topsecret999"
        event = _make_crash_event(message=f"db_password={secret}")
        result = scrub_and_render(event=event, render_fn=_simple_render, scrub_fn=_scrub_fn)
        assert secret not in result

    def test_scrub_applied_to_stack_code(self) -> None:
        """
        Given a crash event with a JWT in a stack frame code line,
        When scrub_and_render() is called,
        Then the JWT header is masked in the rendered output (R7, spec §9).
        """
        # Valid JWT structure (three dot-separated base64url segments starting with eyJ)
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyMTIzIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        event = _make_crash_event()
        event["payload"]["stack"][0]["code"] = f"token = '{jwt}'"
        result = scrub_and_render(event=event, render_fn=_simple_render, scrub_fn=_scrub_fn)
        # JWT header portion must be gone from result
        assert "eyJhbGciOiJIUzI1NiJ9" not in result

    def test_scrub_applied_to_custom_text_and_extras_values(self) -> None:
        """
        Given a custom event with a Bearer token in extras,
        When scrub_and_render() is called,
        Then the token value is masked in the rendered output (R7).
        """
        # 'auth_token' key is in KEY_DENYLIST so its value gets replaced entirely
        event = _make_custom_event(
            text="sending request",
            extras={"auth_token": "Bearer supersecret456"},
        )
        result = scrub_and_render(event=event, render_fn=_simple_render, scrub_fn=_scrub_fn)
        assert "supersecret456" not in result

    def test_scrub_applied_to_context_values(self) -> None:
        """
        Given an event whose context dict has 'password' key (in KEY_DENYLIST),
        When scrub_and_render() is called,
        Then the password value is masked in the rendered output (R7).
        """
        event = _make_custom_event()
        event["context"]["password"] = "hunter2"
        result = scrub_and_render(event=event, render_fn=_simple_render, scrub_fn=_scrub_fn)
        assert "hunter2" not in result


class TestOriginalEventUnchanged:
    def test_original_event_unchanged(self) -> None:
        """
        Given any event,
        When scrub_and_render() is called,
        Then the original event dict is NOT mutated (S2).
        """
        secret = "topsecretkeyvalue"
        event = _make_crash_event(message=f"api_key={secret}")
        original_message = event["payload"]["message"]
        original_deep = copy.deepcopy(event)

        scrub_and_render(event=event, render_fn=_simple_render, scrub_fn=_scrub_fn)

        # Original event must be unchanged
        assert event == original_deep
        assert event["payload"]["message"] == original_message

    def test_render_uses_scrubbed_copy_original_dedup_entry_unchanged(self) -> None:
        """
        Given an event with a sensitive key denylist match in context,
        When scrub_and_render() is called,
        Then the scrubbing operates on a copy so the caller's event is intact (S2).
        """
        event = _make_custom_event()
        event["context"]["password"] = "hunter2"
        before_password = event["context"]["password"]

        result = scrub_and_render(event=event, render_fn=_simple_render, scrub_fn=_scrub_fn)

        # Rendered result should have the password masked
        assert "hunter2" not in result
        # But original event's context is still intact
        assert event["context"]["password"] == before_password
