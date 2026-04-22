"""Unit tests for SocketPathDiscovery (Task 2.1).

Tests verify the PORT layer — thin wrapper + error mapping — not the shared kernel
directly (which is covered in Phase 1 test_config_hash.py).
"""
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from snitchbot.client.app.interfaces.i_discovery import IDiscovery
from snitchbot.client.errors import SocketPathError
from snitchbot.client.ports.driven.discovery.socket_path_service import SocketPathDiscovery


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SERVICE = "myservice"
TOKEN = "123456:ABC-DEF"
CHAT_ID = -100123456789


@pytest.fixture()
def discovery() -> SocketPathDiscovery:
    return SocketPathDiscovery()


# ---------------------------------------------------------------------------
# Environment / XDG
# ---------------------------------------------------------------------------


def test_compute_socket_path_uses_xdg_runtime_dir_if_present(
    discovery: SocketPathDiscovery, tmp_path: Path
) -> None:
    """
    Given XDG_RUNTIME_DIR is set to an existing directory,
    When compute_path is called,
    Then the returned path is inside XDG_RUNTIME_DIR.
    """
    with patch.dict("os.environ", {"XDG_RUNTIME_DIR": str(tmp_path)}):
        result = discovery.compute_path(SERVICE, TOKEN, CHAT_ID)

    assert result.parent == tmp_path


def test_compute_socket_path_falls_back_to_tmp_when_xdg_missing(
    discovery: SocketPathDiscovery,
) -> None:
    """
    Given XDG_RUNTIME_DIR is not set,
    When compute_path is called,
    Then the returned path is inside /tmp/snitchbot-<uid>/.
    """
    import os

    env = {k: v for k, v in __import__("os").environ.items() if k != "XDG_RUNTIME_DIR"}
    with patch.dict("os.environ", env, clear=True):
        result = discovery.compute_path(SERVICE, TOKEN, CHAT_ID)

    expected_base = Path(f"/tmp/snitchbot-{os.getuid()}")
    assert result.parent == expected_base


def test_fallback_dir_created_with_0700_permissions(
    discovery: SocketPathDiscovery,
) -> None:
    """
    Given XDG_RUNTIME_DIR is not set,
    When compute_path is called,
    Then the fallback /tmp/snitchbot-<uid>/ directory exists with mode 0700.
    """
    import os

    env = {k: v for k, v in __import__("os").environ.items() if k != "XDG_RUNTIME_DIR"}
    with patch.dict("os.environ", env, clear=True):
        discovery.compute_path(SERVICE, TOKEN, CHAT_ID)

    fallback = Path(f"/tmp/snitchbot-{os.getuid()}")
    assert fallback.exists()
    mode = stat.S_IMODE(fallback.stat().st_mode)
    assert mode == 0o700


# ---------------------------------------------------------------------------
# Determinism & isolation (invariant I1, I3)
# ---------------------------------------------------------------------------


def test_different_tokens_yield_different_paths(
    discovery: SocketPathDiscovery, tmp_path: Path
) -> None:
    """
    Given two distinct tokens with the same service and chat_id (-> I1),
    When compute_path is called for each,
    Then the resulting paths are different.
    """
    with patch.dict("os.environ", {"XDG_RUNTIME_DIR": str(tmp_path)}):
        path_a = discovery.compute_path(SERVICE, "token-AAA", CHAT_ID)
        path_b = discovery.compute_path(SERVICE, "token-BBB", CHAT_ID)

    assert path_a != path_b


def test_different_chat_ids_yield_different_paths(
    discovery: SocketPathDiscovery, tmp_path: Path
) -> None:
    """
    Given two distinct chat_ids with the same service and token,
    When compute_path is called for each,
    Then the resulting paths are different.
    """
    with patch.dict("os.environ", {"XDG_RUNTIME_DIR": str(tmp_path)}):
        path_a = discovery.compute_path(SERVICE, TOKEN, -100111111111)
        path_b = discovery.compute_path(SERVICE, TOKEN, -100222222222)

    assert path_a != path_b


def test_same_config_yields_identical_path_deterministic(
    discovery: SocketPathDiscovery, tmp_path: Path
) -> None:
    """
    Given the same (service, token, chat_id) triple,
    When compute_path is called twice,
    Then both calls return the identical path (deterministic).
    """
    with patch.dict("os.environ", {"XDG_RUNTIME_DIR": str(tmp_path)}):
        path_a = discovery.compute_path(SERVICE, TOKEN, CHAT_ID)
        path_b = discovery.compute_path(SERVICE, TOKEN, CHAT_ID)

    assert path_a == path_b


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def test_compute_path_raises_socket_path_error_on_kernel_failure(
    discovery: SocketPathDiscovery,
) -> None:
    """
    Given the shared kernel compute_socket_path raises an unexpected exception,
    When compute_path is called,
    Then SocketPathError is raised (port layer wraps the exception).
    """
    with patch(
        "snitchbot.client.ports.driven.discovery.socket_path_service.compute_socket_path",
        side_effect=RuntimeError("kernel boom"),
    ):
        with pytest.raises(SocketPathError, match="kernel boom"):
            discovery.compute_path(SERVICE, TOKEN, CHAT_ID)


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_implements_i_discovery_protocol(discovery: SocketPathDiscovery) -> None:
    """
    Given SocketPathDiscovery,
    When checked against IDiscovery,
    Then isinstance returns True (runtime_checkable Protocol).
    """
    assert isinstance(discovery, IDiscovery)
