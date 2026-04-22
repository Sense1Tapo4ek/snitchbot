"""Scrubbing patterns: denylist keys and regex rules.

Pure stdlib. Must stay framework-free (domain layer).
Reference: docs/superpowers/specs/2026-04-11-secret-scrubbing-design.md
"""
import re

PLACEHOLDER: str = "[REDACTED]"

# Substring, case-insensitive match. If any token appears inside the dict key
# (lowercased), the VALUE is replaced entirely with PLACEHOLDER.
KEY_DENYLIST: frozenset[str] = frozenset(
    [
        # Authentication / Authorization
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "bearer",
        "authorization",
        "auth",
        "credentials",
        "api_key",
        "apikey",
        "x_api_key",
        "private_key",
        "privatekey",
        "client_secret",
        "session",
        "sessionid",
        "session_id",
        "cookie",
        "csrf",
        "xsrf",
        "x_csrftoken",
        # Cloud credentials
        "aws_secret_access_key",
        "aws_session_token",
        # Database
        "db_password",
        "database_password",
    ]
)


# Ordered tuple of (pattern_name, compiled_pattern, replacement).
# More specific patterns come first to win overlapping matches.
#
# For simplicity of the public REGEX_PATTERNS shape (pattern_name, compiled),
# we keep replacement as the third element via a helper dict, but the public
# tuple exposes only (name, compiled) to satisfy the task contract.

_PATTERNS_WITH_REPL: tuple[tuple[str, re.Pattern[str], str], ...] = (
    # AWS access key id
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:aws-access-key]"),
    # AWS secret access key (kv form)
    (
        "aws-secret",
        re.compile(
            r"aws_secret_access_key\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?",
            re.IGNORECASE,
        ),
        "[REDACTED:aws-secret]",
    ),
    # GitHub tokens: ghp_, gho_, ghu_, ghs_, ghr_
    (
        "github-token",
        re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
        "[REDACTED:github-token]",
    ),
    # Slack tokens
    (
        "slack-token",
        re.compile(r"xox[aboprs]-[A-Za-z0-9-]{10,}"),
        "[REDACTED:slack-token]",
    ),
    # Stripe secret keys
    (
        "stripe-key",
        re.compile(r"sk_(?:live|test)_[A-Za-z0-9]{24,}"),
        "[REDACTED:stripe-key]",
    ),
    (
        "stripe-restricted-key",
        re.compile(r"rk_(?:live|test)_[A-Za-z0-9]{24,}"),
        "[REDACTED:stripe-restricted-key]",
    ),
    # Google API key
    (
        "google-api-key",
        re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
        "[REDACTED:google-api-key]",
    ),
    # JWT (three dot-separated b64url segments starting with eyJ)
    (
        "jwt",
        re.compile(r"eyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]{10,}"),
        "[REDACTED:jwt]",
    ),
    # PEM private keys (multiline)
    (
        "private-key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
        ),
        "[REDACTED:private-key]",
    ),
    # Authorization: Bearer/Basic/Token <value>
    (
        "auth-header",
        re.compile(
            r"(?i)(Authorization:\s*)(Bearer|Basic|Token)\s+[A-Za-z0-9_\-\.=+/]+"
        ),
        r"\1\2 [REDACTED]",
    ),
    # Standalone Bearer <token> in free text (no "Authorization:" prefix)
    (
        "bearer-free",
        re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.=+/]{8,}"),
        "Bearer [REDACTED]",
    ),
    # DB connection string passwords: scheme://user:pass@host
    (
        "db-url-password",
        re.compile(r"([a-zA-Z][a-zA-Z0-9+.\-]*://[^:/?#\s]+:)[^@\s]+(@)"),
        r"\1[REDACTED]\2",
    ),
    # Telegram bot token: <digits>:<35 chars>
    (
        "tg-bot-token",
        re.compile(r"\b\d{6,10}:[A-Za-z0-9_\-]{35}\b"),
        "[REDACTED:tg-token]",
    ),
    # Generic key=value form for key-ish names
    (
        "generic-kv",
        re.compile(
            r"(?i)([A-Za-z_][A-Za-z0-9_\-]*(?:key|token|secret|password)[A-Za-z0-9_\-]*)"
            r"(\s*[=:]\s*)"
            r"(['\"]?)([^'\"\s,}]+)(\3)"
        ),
        r"\1\2\3[REDACTED]\5",
    ),
)


# Public tuple: (name, compiled_pattern)
REGEX_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, pat) for name, pat, _ in _PATTERNS_WITH_REPL
)


def iter_patterns_with_replacement() -> tuple[tuple[str, re.Pattern[str], str], ...]:
    """Internal accessor used by the scrubbing service."""
    return _PATTERNS_WITH_REPL


__all__ = [
    "KEY_DENYLIST",
    "PLACEHOLDER",
    "REGEX_PATTERNS",
    "iter_patterns_with_replacement",
]
