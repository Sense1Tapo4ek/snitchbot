"""Unit tests for config_hash_service (shared kernel).

Covers:
- compute_config_hash determinism, sensitivity, hex format, edge cases.
- compute_socket_path XDG_RUNTIME_DIR handling, /tmp fallback, permissions.

Per spec §5.1: blake2b(digest_size=6) -> 12-char lowercase hex.
"""
import os
import re
import shutil
import stat
from pathlib import Path

import pytest

from snitchbot.shared.domain.services.config_hash_service import (
    compute_config_hash,
    compute_socket_path,
)

HEX_RE = re.compile(r"^[0-9a-f]+$")
EXPECTED_HEX_LEN = 12  # digest_size=6 bytes -> 12 hex chars (spec §5.1)


class TestComputeConfigHash:
    def test_compute_config_hash_deterministic_same_input(self):
        """
        Given the same (token, chat_id),
        When compute_config_hash is called twice,
        Then both calls return the identical hash.
        """
        h1 = compute_config_hash("secret-token", "12345")
        h2 = compute_config_hash("secret-token", "12345")
        assert h1 == h2

    def test_compute_config_hash_differs_on_token_change(self):
        """
        Given two different tokens,
        When computing hashes for the same chat_id,
        Then the hashes differ.
        """
        h1 = compute_config_hash("token-a", "42")
        h2 = compute_config_hash("token-b", "42")
        assert h1 != h2

    def test_compute_config_hash_differs_on_chat_id_change(self):
        """
        Given the same token and two different chat_ids,
        When computing hashes,
        Then the hashes differ.
        """
        h1 = compute_config_hash("token-a", "42")
        h2 = compute_config_hash("token-a", "43")
        assert h1 != h2

    def test_compute_config_hash_hex_length(self):
        """
        Given any input,
        When compute_config_hash is called,
        Then the result has length 12 (digest_size=6 bytes).
        """
        h = compute_config_hash("token", "1")
        assert len(h) == EXPECTED_HEX_LEN

    def test_compute_config_hash_stable_with_null_chars_in_token(self):
        """
        Given a token containing a null byte,
        When computing hash,
        Then no exception is raised and the primary NA6 boundary-collision
        case ("a\\x00b","c") vs ("ab","c") yields distinct hashes.

        Note: byte-stream semantics mean that ("a\\x00b","c") and
        ("a","b\\x00c") DO collide by design — the separator is just a
        stable boundary within the digest, not a content marker. NA6 only
        prevents the "no separator at all" boundary-collision.
        """
        h_null_in_token = compute_config_hash("a\x00b", "c")
        h_boundary = compute_config_hash("ab", "c")
        assert h_null_in_token != h_boundary
        assert len(h_null_in_token) == EXPECTED_HEX_LEN
        assert HEX_RE.match(h_null_in_token)

    def test_compute_config_hash_stable_with_negative_chat_id(self):
        """
        Given a negative Telegram group chat_id (int),
        When computing hash,
        Then no exception is raised.
        """
        h = compute_config_hash("token", -1001234567890)
        assert len(h) == EXPECTED_HEX_LEN
        assert HEX_RE.match(h)

    def test_compute_config_hash_handles_unicode_token(self):
        """
        Given a non-ASCII unicode token,
        When computing hash,
        Then no exception is raised (defensive; real TG tokens are ASCII).
        """
        h = compute_config_hash("ツトークン", "42")
        assert len(h) == EXPECTED_HEX_LEN
        assert HEX_RE.match(h)

    def test_compute_config_hash_returns_lowercase_hex(self):
        """
        Given any input,
        When computing hash,
        Then result matches ^[0-9a-f]+$.
        """
        h = compute_config_hash("TOKEN-Mixed-CASE", "42")
        assert HEX_RE.match(h), f"not lowercase hex: {h!r}"

    def test_compute_config_hash_accepts_int_chat_id_equivalent_to_str(self):
        """
        Given chat_id=42 (int) vs chat_id="42" (str),
        When computing hashes,
        Then both yield the same value (str() coercion).
        """
        assert compute_config_hash("t", 42) == compute_config_hash("t", "42")


class TestComputeSocketPath:
    def test_compute_socket_path_uses_xdg_runtime_dir_if_available(
        self, monkeypatch, tmp_path: Path
    ):
        """
        Given XDG_RUNTIME_DIR points to an existing directory,
        When compute_socket_path is called,
        Then the socket path is placed inside that directory.
        """
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

        path = compute_socket_path("myservice", "token", "42")

        assert path.parent == tmp_path
        assert path.name.startswith("snitchbot-myservice-")
        assert path.suffix == ".sock"

    def test_compute_socket_path_falls_back_to_tmp_mylib_uid(
        self, monkeypatch
    ):
        """
        Given XDG_RUNTIME_DIR is unset,
        When compute_socket_path is called,
        Then the path is under /tmp/snitchbot-<uid>/.
        """
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        fake_uid = 987654
        monkeypatch.setattr(os, "getuid", lambda: fake_uid)

        fallback = Path(f"/tmp/snitchbot-{fake_uid}")
        if fallback.exists():
            shutil.rmtree(fallback)

        try:
            path = compute_socket_path("svc", "token", "42")
            assert path.parent == fallback
        finally:
            if fallback.exists():
                shutil.rmtree(fallback)

    def test_compute_socket_path_creates_fallback_dir_with_0700(
        self, monkeypatch
    ):
        """
        Given the fallback path is used and the dir does not exist,
        When compute_socket_path is called,
        Then /tmp/snitchbot-<uid>/ is created with mode 0700.
        """
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        fake_uid = 987655
        monkeypatch.setattr(os, "getuid", lambda: fake_uid)

        fallback = Path(f"/tmp/snitchbot-{fake_uid}")
        if fallback.exists():
            shutil.rmtree(fallback)

        try:
            compute_socket_path("svc", "token", "42")
            assert fallback.is_dir()
            mode = stat.S_IMODE(fallback.stat().st_mode)
            assert mode == 0o700, f"expected 0o700, got {oct(mode)}"
        finally:
            if fallback.exists():
                shutil.rmtree(fallback)

    def test_compute_socket_path_filename_format(
        self, monkeypatch, tmp_path: Path
    ):
        """
        Given a (service, token, chat_id),
        When compute_socket_path is called,
        Then filename equals f"snitchbot-{service}-{hash}.sock".
        """
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

        fp = compute_config_hash("token", "42")
        path = compute_socket_path("svc", "token", "42")

        assert path.name == f"snitchbot-svc-{fp}.sock"

    def test_compute_socket_path_client_sidecar_symmetry(
        self, monkeypatch, tmp_path: Path
    ):
        """
        Given the same inputs,
        When compute_socket_path is called twice (simulating client and sidecar),
        Then both return the identical path — proving single source of truth.
        """
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

        client_path = compute_socket_path("svc", "secret", "42")
        sidecar_path = compute_socket_path("svc", "secret", "42")

        assert client_path == sidecar_path

    def test_compute_socket_path_xdg_ignored_if_not_a_dir(
        self, monkeypatch, tmp_path: Path
    ):
        """
        Given XDG_RUNTIME_DIR points to a non-existent path,
        When compute_socket_path is called,
        Then the fallback /tmp path is used.
        """
        bogus = tmp_path / "does-not-exist"
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(bogus))
        fake_uid = 987656
        monkeypatch.setattr(os, "getuid", lambda: fake_uid)

        fallback = Path(f"/tmp/snitchbot-{fake_uid}")
        if fallback.exists():
            shutil.rmtree(fallback)

        try:
            path = compute_socket_path("svc", "t", "42")
            assert path.parent == fallback
        finally:
            if fallback.exists():
                shutil.rmtree(fallback)
