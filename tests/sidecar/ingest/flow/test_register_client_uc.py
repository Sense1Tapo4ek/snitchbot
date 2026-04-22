"""Flow tests for RegisterClientUseCase.

Invariants validated: A4 (client stored after ack), I8 (config_hash mismatch -> reject).
"""
import os
import time

from snitchbot.sidecar.ingest.app.use_cases.register_client_uc import RegisterClientUseCase
from snitchbot.sidecar.ingest.domain.client_registry_agg import ClientRegistry
from snitchbot.sidecar.session.domain.session_agg import SidecarSession

SIDECAR_CONFIG_HASH = "aabbcc112233"
MATCHING_HASH = SIDECAR_CONFIG_HASH
MISMATCHED_HASH = "000000000000"

HELLO_VALID: dict = {
    "type": "hello",
    "pid": 42,
    "service": "orders-api",
    "config_hash": MATCHING_HASH,
    "started_at": 1712828400.0,
    "anomaly_config": None,
}


def _make_uc(
    config_hash: str = SIDECAR_CONFIG_HASH,
) -> tuple[RegisterClientUseCase, ClientRegistry, SidecarSession]:
    registry = ClientRegistry()
    session = SidecarSession(started_at=time.monotonic())
    uc = RegisterClientUseCase(
        _registry=registry,
        _session=session,
        _config_hash=config_hash,
    )
    return uc, registry, session


class TestValidHello:
    def test_valid_hello_returns_ack_with_sidecar_pid_and_version(self):
        """
        Given a valid hello matching config_hash,
        When calling RegisterClientUseCase,
        Then ack contains sidecar_pid (os.getpid()) and sidecar_lib_version.
        """
        # Arrange
        uc, _, _ = _make_uc()

        # Act
        result = uc(hello=HELLO_VALID, sender_addr="client-addr-1")

        # Assert
        assert result["sidecar_pid"] == os.getpid()
        assert "sidecar_lib_version" in result

    def test_ack_contains_type_hello_ack(self):
        """
        Given a valid hello,
        When calling RegisterClientUseCase,
        Then result type is 'hello_ack'.
        """
        # Arrange
        uc, _, _ = _make_uc()

        # Act
        result = uc(hello=HELLO_VALID, sender_addr="client-addr-1")

        # Assert
        assert result["type"] == "hello_ack"

    def test_client_stored_in_registry_after_ack(self):
        """
        Given a valid hello (invariant A4),
        When calling RegisterClientUseCase,
        Then client with matching pid is stored in registry.
        """
        # Arrange
        uc, registry, _ = _make_uc()

        # Act
        uc(hello=HELLO_VALID, sender_addr="client-addr-1")

        # Assert
        client = registry.get_by_pid(HELLO_VALID["pid"])
        assert client is not None
        assert client.pid == HELLO_VALID["pid"]
        assert client.service == HELLO_VALID["service"]
        assert client.config_hash == MATCHING_HASH
        assert client.addr == "client-addr-1"

    def test_duplicate_hello_same_pid_is_idempotent(self):
        """
        Given the same pid sends hello twice,
        When calling RegisterClientUseCase twice,
        Then no error is raised and client is updated (not duplicated).
        """
        # Arrange
        uc, registry, _ = _make_uc()

        # Act — first hello
        uc(hello=HELLO_VALID, sender_addr="addr-1")
        # Act — second hello (same pid, different addr)
        result = uc(hello={**HELLO_VALID, "started_at": 999.0}, sender_addr="addr-2")

        # Assert — ack returned both times, registry has exactly one entry
        assert result["type"] == "hello_ack"
        assert len(registry.all_pids()) == 1
        # addr updated to latest
        assert registry.get_by_pid(HELLO_VALID["pid"]).addr == "addr-2"

    def test_session_marked_first_hello(self):
        """
        Given a valid hello,
        When calling RegisterClientUseCase,
        Then session.first_hello_received becomes True.
        """
        # Arrange
        uc, _, session = _make_uc()
        assert not session.first_hello_received

        # Act
        uc(hello=HELLO_VALID, sender_addr="client-addr-1")

        # Assert
        assert session.first_hello_received


class TestConfigMismatch:
    def test_config_hash_mismatch_returns_reject(self):
        """
        Given hello with wrong config_hash (invariant I8),
        When calling RegisterClientUseCase,
        Then result is a reject dict (not registered).
        """
        # Arrange
        uc, registry, _ = _make_uc()
        bad_hello = {**HELLO_VALID, "config_hash": MISMATCHED_HASH}

        # Act
        result = uc(hello=bad_hello, sender_addr="client-addr-1")

        # Assert
        assert result["type"] == "reject"
        assert registry.get_by_pid(bad_hello["pid"]) is None

    def test_reject_contains_type_reject_and_reason(self):
        """
        Given hello with wrong config_hash,
        When calling RegisterClientUseCase,
        Then reject dict contains both 'type' and 'reason' fields.
        """
        # Arrange
        uc, _, _ = _make_uc()
        bad_hello = {**HELLO_VALID, "config_hash": MISMATCHED_HASH}

        # Act
        result = uc(hello=bad_hello, sender_addr="client-addr-1")

        # Assert
        assert result["type"] == "reject"
        assert "reason" in result
        assert result["reason"]  # non-empty string
