"""Unit tests for secret scrubbing service.

References spec: docs/superpowers/specs/2026-04-11-secret-scrubbing-design.md
Invariants: S1-S12 (§10 of the spec).
"""
import copy

import pytest

from snitchbot.shared.domain.services import (
    KEY_DENYLIST,
    PLACEHOLDER,
    REGEX_PATTERNS,
    scrub_event,
    scrub_string,
    scrub_value,
)


# ---------------------------------------------------------------------------
# Layer A: key-based denylist (S4)
# ---------------------------------------------------------------------------


class TestDenylist:
    def test_denylist_substring_case_insensitive(self) -> None:
        """
        Given keys like 'Authorization' and 'my_api_key_for_stripe',
        When scrubbing a dict,
        Then values are replaced entirely with the placeholder.
        Invariant: S4 (substring, case-insensitive match).
        """
        src = {
            "Authorization": "Bearer some-legit-looking-val",
            "my_api_key_for_stripe": "plain_value_12345",
            "normal_field": "hello",
        }
        out = scrub_value(None, src)
        assert out["Authorization"] == PLACEHOLDER
        assert out["my_api_key_for_stripe"] == PLACEHOLDER
        assert out["normal_field"] == "hello"

    def test_denylist_frozenset_contains_core_keys(self) -> None:
        """S4: denylist contains critical auth tokens."""
        for token in ("password", "secret", "token", "api_key", "authorization"):
            assert token in KEY_DENYLIST


# ---------------------------------------------------------------------------
# Layer B: regex-based string scrubbing
# ---------------------------------------------------------------------------


class TestRegexPatterns:
    def test_regex_aws_access_key_redacted(self) -> None:
        """Positive: AWS access key AKIA... is masked. S3/S5."""
        text = "key=AKIAABCDEFGHIJKLMNOP in log"
        result = scrub_string(text)
        assert "AKIAABCDEFGHIJKLMNOP" not in result
        assert "REDACTED" in result

    def test_regex_github_token_ghp_redacted(self) -> None:
        """Positive: GitHub ghp_ token masked. S3/S5."""
        text = "token=ghp_1234567890abcdefghijklmnopqrstuvwxyz"
        result = scrub_string(text)
        assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in result
        assert "REDACTED" in result

    def test_regex_github_token_ghs_redacted(self) -> None:
        """Positive: GitHub ghs_ server token masked. S3/S5."""
        text = "creds ghs_abcdefghijklmnopqrstuvwxyz0123456789"
        result = scrub_string(text)
        assert "ghs_abcdefghijklmnopqrstuvwxyz0123456789" not in result
        assert "REDACTED" in result

    def test_regex_slack_token_redacted(self) -> None:
        """Positive: Slack xoxb- token masked. S3/S5."""
        text = "slack=xoxb-1234567890-abcdef"
        result = scrub_string(text)
        assert "xoxb-1234567890-abcdef" not in result
        assert "REDACTED" in result

    def test_regex_slack_xoxo_refresh_token_redacted(self) -> None:
        """Positive: Slack xoxo- refresh token masked. Spec §4.2 char class xox[aboprs]."""
        text = "slack=xoxo-12345-abcdefghij"
        result = scrub_string(text)
        assert "xoxo-12345-abcdefghij" not in result
        assert "REDACTED" in result

    def test_regex_stripe_key_redacted(self) -> None:
        """Positive: Stripe sk_live/sk_test key masked. S3/S5."""
        text = "pay sk_live_abcdefghijklmnopqrstuvwx and sk_test_ABCDEFGHIJKLMNOPQRSTUVWX"
        result = scrub_string(text)
        assert "sk_live_abcdefghijklmnopqrstuvwx" not in result
        assert "sk_test_ABCDEFGHIJKLMNOPQRSTUVWX" not in result
        assert "REDACTED" in result

    def test_regex_google_api_key_redacted(self) -> None:
        """Positive: Google AIza... key masked. S3/S5."""
        text = "google=AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7R"
        result = scrub_string(text)
        assert "AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6Q7R" not in result
        assert "REDACTED" in result

    def test_regex_jwt_redacted(self) -> None:
        """Positive: JWT (three dot-separated base64 segments) masked. S3/S5."""
        text = (
            "Authorization header has "
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        result = scrub_string(text)
        assert "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0" not in result
        assert "REDACTED" in result

    def test_regex_pem_private_key_redacted(self) -> None:
        """Positive: multiline PEM private key masked. S3/S5."""
        text = (
            "header\n"
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEpAIBAAKCAQEA...\n"
            "multiple lines of base64\n"
            "-----END RSA PRIVATE KEY-----\n"
            "footer"
        )
        result = scrub_string(text)
        assert "MIIEpAIBAAKCAQEA" not in result
        assert "REDACTED" in result
        assert "header" in result
        assert "footer" in result

    def test_regex_authorization_bearer_header_keeps_scheme(self) -> None:
        """Edge: Authorization Bearer header keeps scheme tag. S5."""
        text = "Authorization: Bearer abc123xyzTOKEN"
        result = scrub_string(text)
        assert "abc123xyzTOKEN" not in result
        assert "Bearer" in result
        assert "REDACTED" in result

    def test_regex_db_url_redacts_only_password(self) -> None:
        """Edge: db URL — only password is redacted, user/host preserved."""
        text = "postgresql://admin:supersecret@db.example.com:5432/orders"
        result = scrub_string(text)
        assert "supersecret" not in result
        assert "admin" in result
        assert "db.example.com" in result
        assert "REDACTED" in result

    def test_regex_generic_api_key_equals_form(self) -> None:
        """Positive: generic key=value form is redacted. S3/S5."""
        text = "config my_api_key=abc123DEF456ghi789JKL012mno345"
        result = scrub_string(text)
        assert "abc123DEF456ghi789JKL012mno345" not in result
        assert "REDACTED" in result

    def test_regex_tg_bot_token_redacted(self) -> None:
        """Positive: Telegram bot token masked. Invariant S10."""
        # TG token format: <digits>:<exactly 35 chars>
        token = "123456789:AAEabcdefghijklmnopqrstuvwxyz012345"
        assert len(token.split(":", 1)[1]) == 35
        text = f"telegram {token}"
        result = scrub_string(text)
        assert token not in result
        assert "REDACTED" in result


# ---------------------------------------------------------------------------
# Negative: legitimate content must not be touched
# ---------------------------------------------------------------------------


class TestNegativeNoFalsePositives:
    def test_negative_uuid_not_redacted(self) -> None:
        """Negative: UUIDs look random but are not secrets."""
        text = "request_id=550e8400-e29b-41d4-a716-446655440000"
        result = scrub_string(text)
        assert "550e8400-e29b-41d4-a716-446655440000" in result

    def test_negative_sha256_hash_not_redacted(self) -> None:
        """Negative: 64-char hex hash is not a false positive."""
        text = "sha256 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        result = scrub_string(text)
        assert (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            in result
        )

    def test_negative_file_path_not_redacted(self) -> None:
        """Negative: POSIX paths must pass through."""
        text = "/usr/local/bin/python"
        assert scrub_string(text) == text

    def test_negative_normal_sentence_unchanged(self) -> None:
        """Negative: ordinary English prose is untouched."""
        text = "User authorized successfully at 2026-04-11"
        assert scrub_string(text) == text


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------


class TestInvariants:
    def test_idempotence_rescrub_same(self) -> None:
        """S7: double-scrub is a no-op."""
        text = "aws=AKIAABCDEFGHIJKLMNOP jwt=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sig_abcdef"
        once = scrub_string(text)
        twice = scrub_string(once)
        assert once == twice

    def test_unicode_input_does_not_raise(self) -> None:
        """Edge: unicode strings must not raise on scrubbing."""
        text = "пароль=secret123 и токен"
        # Must not raise; content may or may not be scrubbed but no crash.
        result = scrub_string(text)
        assert isinstance(result, str)

    def test_nested_dict_recursive_scrub(self) -> None:
        """S3: nested dicts are recursively scrubbed (key + regex layers)."""
        src = {
            "level1": {
                "level2": {
                    "password": "hunter2",
                    "note": "sk_live_abcdefghijklmnopqrstuvwx",
                },
            },
        }
        out = scrub_value(None, src)
        assert out["level1"]["level2"]["password"] == PLACEHOLDER
        assert "sk_live_abcdefghijklmnopqrstuvwx" not in out["level1"]["level2"]["note"]

    def test_number_values_untouched(self) -> None:
        """S8: numbers, bools, None are never scrubbed."""
        src = {"count": 42, "ratio": 0.5, "flag": True, "empty": None}
        out = scrub_value(None, src)
        assert out == {"count": 42, "ratio": 0.5, "flag": True, "empty": None}

    def test_function_and_file_names_untouched(self) -> None:
        """S9: qualnames and filenames are not scrubbed (no regex match)."""
        assert scrub_string("snitchbot.client.api.notify") == "snitchbot.client.api.notify"
        assert scrub_string("src/mylib/sidecar/main.py") == "src/mylib/sidecar/main.py"

    def test_scrub_returns_copy_original_unchanged(self) -> None:
        """S2: scrubber does not mutate its input."""
        event = {
            "kind": "custom",
            "payload": {
                "text": "token=ghp_1234567890abcdefghijklmnopqrstuvwxyz",
                "extras": {"password": "hunter2"},
            },
            "context": {"api_key": "raw"},
        }
        snapshot = copy.deepcopy(event)
        scrubbed = scrub_event(event)
        assert event == snapshot
        assert scrubbed is not event

    def test_chat_id_not_scrubbed_not_present(self) -> None:
        """S11: 'chat_id' is not in denylist and passes through."""
        assert not any("chat_id" in tok for tok in KEY_DENYLIST)
        src = {"chat_id": -10012345678}
        assert scrub_value(None, src) == {"chat_id": -10012345678}

    def test_placeholder_constant_length(self) -> None:
        """S7: placeholder is a stable constant."""
        assert PLACEHOLDER == "[REDACTED]"
        assert isinstance(PLACEHOLDER, str)

    def test_regex_patterns_is_ordered_tuple(self) -> None:
        """S5: patterns are in a fixed-order container."""
        assert isinstance(REGEX_PATTERNS, tuple)
        assert len(REGEX_PATTERNS) > 0


# ---------------------------------------------------------------------------
# Event-kind coverage (spec §7)
# ---------------------------------------------------------------------------


class TestScrubEventByKind:
    def test_scrub_event_by_kind_crash_paths(self) -> None:
        """Crash: payload.message and stack[*].code are scrubbed. S3/S7."""
        event = {
            "kind": "crash",
            "payload": {
                "message": "boom token=ghp_1234567890abcdefghijklmnopqrstuvwxyz",
                "stack": [
                    {
                        "file": "a.py",
                        "line": 10,
                        "func": "f",
                        "code": "call(AKIAABCDEFGHIJKLMNOP)",
                    },
                ],
            },
            "context": {"password": "hunter2"},
        }
        out = scrub_event(event)
        assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in out["payload"]["message"]
        assert "AKIAABCDEFGHIJKLMNOP" not in out["payload"]["stack"][0]["code"]
        assert out["context"]["password"] == PLACEHOLDER
        # Non-scrubbed structural fields preserved
        assert out["payload"]["stack"][0]["file"] == "a.py"
        assert out["payload"]["stack"][0]["line"] == 10

    def test_scrub_event_by_kind_custom_paths(self) -> None:
        """Custom: text, extras, exception.message/stack are scrubbed."""
        event = {
            "kind": "custom",
            "payload": {
                "text": "see token=ghp_1234567890abcdefghijklmnopqrstuvwxyz",
                "extras": {
                    "user": "alice",
                    "api_key": "raw-secret",
                    "nested": {"password": "hunter2"},
                },
                "exception": {
                    "message": "fail AKIAABCDEFGHIJKLMNOP",
                    "stack": [
                        {"file": "x.py", "code": "op(sk_live_abcdefghijklmnopqrstuvwx)"},
                    ],
                },
            },
            "context": {},
        }
        out = scrub_event(event)
        assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in out["payload"]["text"]
        assert out["payload"]["extras"]["user"] == "alice"
        assert out["payload"]["extras"]["api_key"] == PLACEHOLDER
        assert out["payload"]["extras"]["nested"]["password"] == PLACEHOLDER
        assert "AKIAABCDEFGHIJKLMNOP" not in out["payload"]["exception"]["message"]
        assert (
            "sk_live_abcdefghijklmnopqrstuvwx"
            not in out["payload"]["exception"]["stack"][0]["code"]
        )

    def test_scrub_event_by_kind_watchdog_stuck_task_stack_strings(self) -> None:
        """Watchdog: stuck_tasks[*].stack strings are scrubbed."""
        event = {
            "kind": "watchdog",
            "payload": {
                "stuck_tasks": [
                    {
                        "name": "task-1",
                        "coro": "my_coro",
                        "stack": [
                            "call(AKIAABCDEFGHIJKLMNOP)",
                            "await x",
                        ],
                    },
                ],
            },
            "context": {},
        }
        out = scrub_event(event)
        assert "AKIAABCDEFGHIJKLMNOP" not in out["payload"]["stuck_tasks"][0]["stack"][0]
        assert out["payload"]["stuck_tasks"][0]["stack"][1] == "await x"
        assert out["payload"]["stuck_tasks"][0]["name"] == "task-1"
        assert out["payload"]["stuck_tasks"][0]["coro"] == "my_coro"

    @pytest.mark.parametrize("kind", ["slow_call", "anomaly", "lifecycle"])
    def test_scrub_skips_slow_call_and_anomaly(self, kind: str) -> None:
        """Spec §7: slow_call, anomaly, lifecycle payloads are not touched."""
        event = {
            "kind": kind,
            "payload": {
                "func_qualname": "snitchbot.client.api.notify",
                "duration_ms": 1500,
                "details": "token=ghp_1234567890abcdefghijklmnopqrstuvwxyz",
            },
            "context": {},
        }
        out = scrub_event(event)
        # payload should be preserved byte-for-byte
        assert out["payload"] == event["payload"]
