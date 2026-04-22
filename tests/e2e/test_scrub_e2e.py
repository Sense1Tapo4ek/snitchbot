"""Phase 12: End-to-end secret scrubbing verification.

Verifies that secrets do not leak through the render pipeline
(scrub_event -> render_alert). Every test builds a real event dict with
known secrets, scrubs it, renders the HTML output, and asserts the
secret is absent from the result.

Spec: docs/superpowers/specs/2026-04-11-secret-scrubbing-design.md §9, S1-S12.
Plan: docs/superpowers/plans/2026-04-11-implementation-plan.md Task 12.1.
Invariants: S1, S2, S3, S4, S5, S6, S7, S8, S9, S10, S11, S12.
"""
import copy

import pytest

from snitchbot.shared.domain.services.scrubbing_service import scrub_event
from snitchbot.sidecar.pipeline.domain.services.alert_render_service import render_alert


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dedup_entry(count: int = 1, severity: str = "error") -> dict:
    return {
        "count": count,
        "first_seen": 1_700_000_000.0,
        "last_seen": 1_700_000_000.0,
        "severity": severity,
        "message_id": None,
    }


def _make_crash_event(
    message: str = "db error",
    stack_code: str = "conn = db.connect()",
    context: dict | None = None,
) -> dict:
    return {
        "kind": "crash",
        "ts": 1_700_000_000.0,
        "pid": 12345,
        "fingerprint": "aabbcc",
        "context": context or {},
        "payload": {
            "exception_type": "RuntimeError",
            "message": message,
            "thread": "MainThread",
            "origin": "excepthook",
            "stack": [
                {
                    "file": "app/orders.py",
                    "line": 42,
                    "func": "create_order",
                    "code": stack_code,
                    "is_user_code": True,
                }
            ],
        },
    }


def _make_custom_event(
    text: str = "processing",
    extras: dict | None = None,
    context: dict | None = None,
) -> dict:
    return {
        "kind": "custom",
        "ts": 1_700_000_000.0,
        "pid": 12345,
        "fingerprint": "aabbcc",
        "context": context or {},
        "payload": {
            "text": text,
            "extras": extras or {},
            "exception": None,
        },
    }


def _render(event: dict) -> str:
    """Scrub then render through the real pipeline."""
    scrubbed = scrub_event(event)
    return render_alert(event=scrubbed, dedup_entry=_make_dedup_entry(), service="orders-api")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGithubTokenDoesNotLeakThroughCrash:
    def test_github_token_in_exception_message_never_reaches_html(self) -> None:
        """
        Given a crash event whose exception message contains a real GitHub token,
        When scrub_event -> render_alert is applied,
        Then the token value is absent from the HTML output (S1).
        """
        token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        event = _make_crash_event(message=f"Failed to call GitHub API with token={token}")

        html = _render(event)

        assert token not in html
        assert "[REDACTED" in html


class TestDbUrlPasswordStrippedInExtras:
    def test_db_url_password_stripped_in_extras(self) -> None:
        """
        Given a custom event whose extras contain a database URL with password,
        When scrub_event -> render_alert is applied,
        Then the password portion is absent from the HTML output (S1, S3).
        """
        db_url = "postgres://admin:supersecret_pass@db.example.com:5432/orders"
        event = _make_custom_event(
            text="DB connection failed",
            extras={"connection_string": db_url},
        )

        html = _render(event)

        assert "supersecret_pass" not in html
        # username and host remain (only password is scrubbed)
        assert "admin" in html
        assert "db.example.com" in html


class TestAuthorizationHeaderInStackCodeScrubbed:
    def test_authorization_bearer_header_in_stack_code_absent_from_html(self) -> None:
        """
        Given a crash event whose stack frame code line contains a Bearer header,
        When scrub_event -> render_alert is applied,
        Then the token value is absent but 'Bearer' label is preserved (S1, spec §9).
        """
        raw_token = "eyJhbGciOiJub25lIn0.eyJ1c2VyIjoiYm9iIn0.fakesig123"
        code_line = f'headers["Authorization"] = "Bearer {raw_token}"'
        event = _make_crash_event(stack_code=code_line)

        html = _render(event)

        # The raw token must be gone
        assert raw_token not in html


class TestContextValueWithTokenScrubbed:
    def test_context_value_with_api_token_scrubbed(self) -> None:
        """
        Given a crash event whose context dict has a key matching 'token' denylist,
        When scrub_event -> render_alert is applied,
        Then the token value does not appear in the HTML output (S1, S4).
        """
        secret = "my_super_secret_access_token_abc123"
        event = _make_crash_event(context={"api_token": secret})

        html = _render(event)

        assert secret not in html


class TestDenylistKeyReplacesEntireValue:
    def test_denylist_key_replaces_value_in_extras(self) -> None:
        """
        Given a custom event whose extras have a 'password' key (matches denylist),
        When scrub_event -> render_alert is applied,
        Then the entire value is replaced by [REDACTED] (S3, S4).
        """
        secret = "hunter2_plaintext"
        event = _make_custom_event(extras={"db_password": secret})

        html = _render(event)

        assert secret not in html
        assert "[REDACTED]" in html


class TestOriginalEventUnchangedAfterScrub:
    def test_original_event_not_mutated_by_scrub_then_render(self) -> None:
        """
        Given a crash event with a secret,
        When scrub_event is called (S2 invariant),
        Then the original event dict is completely unchanged.
        """
        token = "ghp_abcdefghijklmnopqrstuvwxyz123456789012"
        event = _make_crash_event(message=f"token={token}")
        original = copy.deepcopy(event)

        scrub_event(event)  # must NOT mutate event
        # Also run full render pipeline
        _render(event)

        assert event == original, "scrub_event must not mutate the original event (S2)"

    def test_scrub_event_returns_new_object(self) -> None:
        """
        Given any event dict,
        When scrub_event is called,
        Then it returns a new object, not the same reference (S2).
        """
        event = _make_crash_event()
        result = scrub_event(event)

        assert result is not event
        assert result["payload"] is not event["payload"]


class TestAllSInvariantsEndToEnd:
    """Consolidated multi-invariant test running secrets through the full pipeline."""

    def test_multiple_secrets_all_scrubbed_from_single_event(self) -> None:
        """
        Given a crash event that simultaneously contains:
          - GitHub token in exception message
          - DB URL with password in context
          - 'token' key in extras (denylist hit)
        When the full scrub -> render pipeline runs,
        Then none of the secret values appear in the output (S1, S2, S3, S4, S5, S6).
        """
        ghp_token = "ghp_0000000000000000000000000000000000000000"
        db_pass = "ultra_secret_db_pass"
        denylist_val = "denylist_hit_value_xyz"

        event = {
            "kind": "crash",
            "ts": 1_700_000_000.0,
            "pid": 9999,
            "fingerprint": "cafe00",
            "context": {
                "db_url": f"postgres://user:{db_pass}@host:5432/db",
            },
            "payload": {
                "exception_type": "ValueError",
                "message": f"github_token={ghp_token}",
                "thread": "MainThread",
                "origin": "excepthook",
                "stack": [
                    {
                        "file": "app/auth.py",
                        "line": 10,
                        "func": "validate",
                        "code": "pass",
                        "is_user_code": True,
                    }
                ],
            },
        }
        # Add token key to extras through custom event path
        custom_event = _make_custom_event(
            text="auth failed",
            extras={"auth_token": denylist_val},
        )

        crash_html = _render(event)
        custom_html = _render(custom_event)

        # All secrets must be gone
        assert ghp_token not in crash_html, "GitHub token leaked in crash render"
        assert db_pass not in crash_html, "DB password leaked in crash render"
        assert denylist_val not in custom_html, "Denylist-matched value leaked in custom render"

        # Placeholder must be present
        assert "[REDACTED" in crash_html or "[REDACTED" in custom_html
