"""Flow tests for hello_service (Task 2.4).

Tests cover:
- build_hello payload shape matches spec (§5.4)
- anomaly_config is canonicalized via AnomalyConfig.resolve()
- perform_handshake returns ack on success within timeout
- perform_handshake raises HandshakeTimeoutError when recv returns None
- perform_handshake raises HandshakeRejectedError when recv returns hello_reject
- HandshakeRejectedError carries the reason from the reject message
"""

import msgpack
import pytest

from snitchbot.client.errors import HandshakeRejectedError, HandshakeTimeoutError
from snitchbot.client.ports.driven.handshake.hello_service import (
    build_hello,
    perform_handshake,
)
from snitchbot.shared.domain.anomaly_config_vo import AnomalyConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pack(obj: dict) -> bytes:
    return msgpack.packb(obj, use_bin_type=True)


def _make_ack(**extra) -> bytes:
    return _pack({"type": "hello_ack", "sidecar_pid": 9999, "sidecar_lib_version": "0.1.0", **extra})


def _make_reject(reason: str = "version_mismatch") -> bytes:
    return _pack({"type": "reject", "reason": reason})


# ---------------------------------------------------------------------------
# build_hello
# ---------------------------------------------------------------------------


class TestHelloMessageShape:
    def test_hello_message_shape_matches_spec(self):
        """
        Given: arbitrary pid, service, config_hash, started_at, and anomaly_config
        When: build_hello is called
        Then: returned dict contains exactly the required keys with correct values
        """
        # Arrange
        pid = 12345
        service = "my-service"
        config_hash = "abc123"
        started_at = 1_700_000_000.0
        anomaly_config = AnomalyConfig.defaults()

        # Act
        payload = build_hello(
            pid=pid,
            service=service,
            config_hash=config_hash,
            started_at=started_at,
            anomaly_config=anomaly_config,
        )

        # Assert
        assert payload["type"] == "hello"
        assert payload["pid"] == pid
        assert payload["service"] == service
        assert payload["config_hash"] == config_hash
        assert payload["started_at"] == started_at
        assert "anomaly_config" in payload
        # All and only the expected top-level keys (role added in Phase 2)
        assert set(payload.keys()) == {
            "type",
            "pid",
            "service",
            "config_hash",
            "started_at",
            "role",
            "anomaly_config",
            "sample_interval_sec",
        }


class TestHelloAnomalyConfigCanonicalization:
    def test_anomaly_config_canonicalized_in_hello(self):
        """
        Given: an AnomalyConfig with fds disabled
        When: build_hello is called
        Then: anomaly_config value equals AnomalyConfig.resolve() output
        """
        # Arrange
        anomaly_config = AnomalyConfig(fds=None)
        expected = anomaly_config.resolve()

        # Act
        payload = build_hello(
            pid=1,
            service="svc",
            config_hash="cafebabe",
            started_at=0.0,
            anomaly_config=anomaly_config,
        )

        # Assert
        assert payload["anomaly_config"] == expected
        assert payload["anomaly_config"]["fds"] is None
        assert payload["anomaly_config"]["rss"] is not None

    def test_all_disabled_anomaly_config_serializes_all_none(self):
        """
        Given: AnomalyConfig.all_disabled()
        When: build_hello is called
        Then: all four detector slots in anomaly_config are None
        """
        # Arrange
        anomaly_config = AnomalyConfig.all_disabled()

        # Act
        payload = build_hello(
            pid=1,
            service="svc",
            config_hash="dead",
            started_at=0.0,
            anomaly_config=anomaly_config,
        )

        # Assert
        ac = payload["anomaly_config"]
        assert ac["rss"] is None
        assert ac["cpu"] is None
        assert ac["fds"] is None
        assert ac["threads"] is None
        assert ac["watchdog"] is None


# ---------------------------------------------------------------------------
# perform_handshake — success path
# ---------------------------------------------------------------------------


class TestPerformHandshakeSuccess:
    def test_hello_ack_within_timeout_returns_ack(self):
        """
        Given: transport_recv returns hello_ack bytes
        When: perform_handshake is called
        Then: returns the decoded ack dict
        """
        # Arrange
        sent_bytes = []

        def transport_send(data: bytes) -> None:
            sent_bytes.append(data)

        ack_bytes = _make_ack()

        def transport_recv(timeout_ms: int) -> bytes | None:
            return ack_bytes

        hello = build_hello(
            pid=42,
            service="svc",
            config_hash="abc",
            started_at=1.0,
            anomaly_config=AnomalyConfig.defaults(),
        )

        # Act
        result = perform_handshake(
            transport_send=transport_send,
            transport_recv=transport_recv,
            hello_payload=hello,
            timeout_ms=500,
        )

        # Assert
        assert result["type"] == "hello_ack"
        assert result["sidecar_pid"] == 9999
        assert result["sidecar_lib_version"] == "0.1.0"

    def test_hello_bytes_sent_before_waiting_for_ack(self):
        """
        Given: transport_send and transport_recv callables
        When: perform_handshake is called
        Then: transport_send is called before transport_recv, with msgpack-encoded payload
        """
        # Arrange
        call_order = []

        def transport_send(data: bytes) -> None:
            call_order.append(("send", data))

        def transport_recv(timeout_ms: int) -> bytes | None:
            call_order.append(("recv", timeout_ms))
            return _make_ack()

        hello = build_hello(
            pid=1,
            service="s",
            config_hash="h",
            started_at=0.0,
            anomaly_config=AnomalyConfig.defaults(),
        )

        # Act
        perform_handshake(
            transport_send=transport_send,
            transport_recv=transport_recv,
            hello_payload=hello,
            timeout_ms=500,
        )

        # Assert — send happens before recv
        assert call_order[0][0] == "send"
        assert call_order[1][0] == "recv"
        # Sent bytes decode back to the hello payload
        decoded = msgpack.unpackb(call_order[0][1], raw=False)
        assert decoded["type"] == "hello"
        assert decoded["pid"] == 1


# ---------------------------------------------------------------------------
# perform_handshake — timeout path
# ---------------------------------------------------------------------------


class TestPerformHandshakeTimeout:
    def test_hello_ack_timeout_raises_HandshakeTimeoutError(self):
        """
        Given: transport_recv returns None (timeout expired)
        When: perform_handshake is called
        Then: HandshakeTimeoutError is raised
        """
        # Arrange
        def transport_send(data: bytes) -> None:
            pass

        def transport_recv(timeout_ms: int) -> bytes | None:
            return None

        hello = build_hello(
            pid=1,
            service="svc",
            config_hash="abc",
            started_at=0.0,
            anomaly_config=AnomalyConfig.defaults(),
        )

        # Act / Assert
        with pytest.raises(HandshakeTimeoutError):
            perform_handshake(
                transport_send=transport_send,
                transport_recv=transport_recv,
                hello_payload=hello,
                timeout_ms=500,
            )

    def test_timeout_ms_forwarded_to_recv(self):
        """
        Given: a specific timeout_ms value
        When: perform_handshake is called
        Then: transport_recv receives the same timeout_ms value
        """
        # Arrange
        received_timeouts = []

        def transport_send(data: bytes) -> None:
            pass

        def transport_recv(timeout_ms: int) -> bytes | None:
            received_timeouts.append(timeout_ms)
            return None

        hello = build_hello(
            pid=1,
            service="svc",
            config_hash="abc",
            started_at=0.0,
            anomaly_config=AnomalyConfig.defaults(),
        )

        # Act / Assert
        with pytest.raises(HandshakeTimeoutError):
            perform_handshake(
                transport_send=transport_send,
                transport_recv=transport_recv,
                hello_payload=hello,
                timeout_ms=250,
            )

        assert received_timeouts == [250]


# ---------------------------------------------------------------------------
# perform_handshake — reject path
# ---------------------------------------------------------------------------


class TestPerformHandshakeReject:
    def test_hello_reject_raises_HandshakeRejectedError(self):
        """
        Given: transport_recv returns a hello_reject message
        When: perform_handshake is called
        Then: HandshakeRejectedError is raised
        """
        # Arrange
        def transport_send(data: bytes) -> None:
            pass

        def transport_recv(timeout_ms: int) -> bytes | None:
            return _make_reject("version_mismatch")

        hello = build_hello(
            pid=1,
            service="svc",
            config_hash="abc",
            started_at=0.0,
            anomaly_config=AnomalyConfig.defaults(),
        )

        # Act / Assert
        with pytest.raises(HandshakeRejectedError):
            perform_handshake(
                transport_send=transport_send,
                transport_recv=transport_recv,
                hello_payload=hello,
                timeout_ms=500,
            )

    def test_hello_reject_contains_reason(self):
        """
        Given: transport_recv returns hello_reject with reason="config_hash_mismatch"
        When: perform_handshake is called
        Then: HandshakeRejectedError.reason equals "config_hash_mismatch"
        """
        # Arrange
        expected_reason = "config_hash_mismatch"

        def transport_send(data: bytes) -> None:
            pass

        def transport_recv(timeout_ms: int) -> bytes | None:
            return _make_reject(expected_reason)

        hello = build_hello(
            pid=1,
            service="svc",
            config_hash="abc",
            started_at=0.0,
            anomaly_config=AnomalyConfig.defaults(),
        )

        # Act
        with pytest.raises(HandshakeRejectedError) as exc_info:
            perform_handshake(
                transport_send=transport_send,
                transport_recv=transport_recv,
                hello_payload=hello,
                timeout_ms=500,
            )

        # Assert
        assert exc_info.value.reason == expected_reason

    def test_hello_reject_without_reason_field_still_raises(self):
        """
        Given: transport_recv returns hello_reject with no reason field
        When: perform_handshake is called
        Then: HandshakeRejectedError is raised (reason defaults to empty string or unknown)
        """
        # Arrange
        def transport_send(data: bytes) -> None:
            pass

        def transport_recv(timeout_ms: int) -> bytes | None:
            return _pack({"type": "reject"})

        hello = build_hello(
            pid=1,
            service="svc",
            config_hash="abc",
            started_at=0.0,
            anomaly_config=AnomalyConfig.defaults(),
        )

        # Act / Assert
        with pytest.raises(HandshakeRejectedError):
            perform_handshake(
                transport_send=transport_send,
                transport_recv=transport_recv,
                hello_payload=hello,
                timeout_ms=500,
            )
