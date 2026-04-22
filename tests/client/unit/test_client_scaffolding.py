"""Phase 2 scaffolding smoke tests — confirm importability and shape."""

from dataclasses import is_dataclass

import pytest

from snitchbot.client.app.interfaces import (
    IDiscovery,
    ISidecarSpawner,
    ITransport,
)
from snitchbot.client.domain.client_state_agg import ClientState
from snitchbot.client.domain.stats_vo import ClientStats
from snitchbot.client.errors import (
    HandshakeRejectedError,
    HandshakeTimeoutError,
    SocketPathError,
    SpawnFailedError,
)
from snitchbot.shared.generics.errors import PortError


class TestClientState:
    def test_client_state_enum_has_four_members(self):
        """Given ClientState, When listing members, Then exactly 4 exist."""
        assert len(list(ClientState)) == 4

    def test_client_state_values_are_strings(self):
        """Given each member, When inspecting value, Then it is a str."""
        for member in ClientState:
            assert isinstance(member.value, str)
        assert ClientState.UNINITIALIZED.value == "uninitialized"
        assert ClientState.CONNECTED.value == "connected"
        assert ClientState.DEGRADED.value == "degraded"
        assert ClientState.DISABLED.value == "disabled"


class TestClientStats:
    def test_client_stats_defaults_all_zero(self):
        """Given a fresh ClientStats, When inspecting fields, Then all zero."""
        stats = ClientStats()
        snap = stats.snapshot()
        assert all(v == 0 for v in snap.values())
        # Sanity: expected counters present.
        assert "events_sent" in snap
        assert "dropped_buffer_full" in snap
        assert "called_before_init" in snap

    def test_client_stats_snapshot_returns_dict(self):
        """Given ClientStats, When snapshot(), Then a plain dict is returned."""
        stats = ClientStats()
        snap = stats.snapshot()
        assert isinstance(snap, dict)

    def test_client_stats_is_mutable_counter(self):
        """Given ClientStats, When incrementing a counter, Then value changes."""
        stats = ClientStats()
        stats.events_sent += 1
        stats.oversized += 3
        assert stats.events_sent == 1
        assert stats.oversized == 3

    def test_client_stats_snapshot_is_copy_not_reference(self):
        """
        Given a snapshot,
        When mutating the underlying stats,
        Then the snapshot remains unchanged.
        """
        stats = ClientStats()
        snap = stats.snapshot()
        stats.events_sent += 42
        assert snap["events_sent"] == 0


class TestClientErrors:
    def test_client_errors_inherit_port_error(self):
        """Given each client error class, Then it subclasses PortError."""
        for cls in (
            HandshakeTimeoutError,
            HandshakeRejectedError,
            SocketPathError,
            SpawnFailedError,
        ):
            assert issubclass(cls, PortError)

    def test_handshake_timeout_not_dataclass(self):
        """Given HandshakeTimeoutError, Then it is not a @dataclass."""
        assert not is_dataclass(HandshakeTimeoutError)
        # And raisable/catchable.
        with pytest.raises(HandshakeTimeoutError):
            raise HandshakeTimeoutError("boom")


class _DummyTransport:
    def __init__(self) -> None:
        self._connected = False

    def connect(self, path):  # noqa: ANN001
        self._connected = True

    def send(self, data: bytes) -> None:
        pass

    def recv(self, timeout_ms: int) -> bytes | None:
        return None

    def close(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected


class _DummyDiscovery:
    def compute_path(self, service, token, chat_id):  # noqa: ANN001
        from pathlib import Path
        return Path("/tmp/x.sock")


class _DummySpawner:
    def spawn(self, *, service, token, chat_id, socket_path, log_path):  # noqa: ANN001
        return 12345


class TestProtocols:
    def test_i_transport_is_protocol(self):
        """Given a structurally-compatible object, Then isinstance works."""
        assert isinstance(_DummyTransport(), ITransport)

    def test_i_discovery_is_protocol(self):
        assert isinstance(_DummyDiscovery(), IDiscovery)

    def test_i_spawner_is_protocol(self):
        assert isinstance(_DummySpawner(), ISidecarSpawner)

