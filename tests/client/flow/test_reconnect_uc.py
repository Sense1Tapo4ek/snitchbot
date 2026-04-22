"""Flow tests for ReconnectUseCase (Task 2.8).

Tests cover:
- Successful reconnect returns CONNECTED
- Failed reconnect returns DEGRADED
- Internal exception never raises (invariant I7)
- compute_backoff exponential sequence: 1, 2, 4, 8, 30, 30, ...
- compute_backoff is capped at 30s for attempts > 4
- stats.sidecar_unavailable incremented on failed reconnect
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from snitchbot.client.app.use_cases.reconnect_uc import ReconnectUseCase, compute_backoff
from snitchbot.client.domain.client_state_agg import ClientState
from snitchbot.client.domain.stats_vo import ClientStats


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_uc(*, transport=None, discovery=None, spawner=None, stats=None):
    transport = transport or MagicMock()
    discovery = discovery or MagicMock()
    spawner = spawner or MagicMock()
    stats = stats or ClientStats()
    return ReconnectUseCase(
        _transport=transport,
        _discovery=discovery,
        _spawner=spawner,
        _stats=stats,
    )


def _make_call_kwargs(**overrides):
    defaults = dict(
        service="svc",
        token="tok",
        chat_id="123",
        attempt=0,
        last_state=ClientState.DEGRADED,
    )
    return {**defaults, **overrides}


# ---------------------------------------------------------------------------
# compute_backoff — pure function
# ---------------------------------------------------------------------------


class TestComputeBackoff:
    def test_compute_backoff_exponential(self):
        """
        Given: attempt values 0 through 3
        When: compute_backoff is called
        Then: returns 1, 2, 4, 8 respectively (powers of 2)
        """
        # Arrange / Act / Assert
        assert compute_backoff(0) == 1.0
        assert compute_backoff(1) == 2.0
        assert compute_backoff(2) == 4.0
        assert compute_backoff(3) == 8.0

    def test_compute_backoff_capped_at_30(self):
        """
        Given: attempt values 4, 5, 10, 100
        When: compute_backoff is called
        Then: all return 30.0 (capped)
        """
        # Arrange / Act / Assert
        assert compute_backoff(4) == 30.0
        assert compute_backoff(5) == 30.0
        assert compute_backoff(10) == 30.0
        assert compute_backoff(100) == 30.0

    def test_compute_backoff_attempt_4_is_capped(self):
        """
        Given: attempt=4 (which would be 16s uncapped)
        When: compute_backoff is called
        Then: returns 30.0 (cap kicks in before 16)
        """
        # The spec says: 1->2->4->8->30, so attempt 4 -> 30 (not 16)
        assert compute_backoff(4) == 30.0


# ---------------------------------------------------------------------------
# ReconnectUseCase — success path
# ---------------------------------------------------------------------------


class TestReconnectSucceeds:
    def test_reconnect_succeeds_returns_connected(self):
        """
        Given: transport.connect succeeds and transport.is_connected is True
        When: ReconnectUseCase is called
        Then: returns ClientState.CONNECTED
        """
        # Arrange
        transport = MagicMock()
        transport.connect.return_value = None
        transport.is_connected = True

        discovery = MagicMock()
        discovery.compute_path.return_value = Path("/tmp/svc.sock")

        uc = _make_uc(transport=transport, discovery=discovery)

        # Act
        result = uc(**_make_call_kwargs())

        # Assert
        assert result == ClientState.CONNECTED


# ---------------------------------------------------------------------------
# ReconnectUseCase — failure path
# ---------------------------------------------------------------------------


class TestReconnectFails:
    def test_reconnect_fails_returns_degraded(self):
        """
        Given: transport.connect raises an exception (socket unavailable)
        When: ReconnectUseCase is called
        Then: returns ClientState.DEGRADED
        """
        # Arrange
        transport = MagicMock()
        transport.connect.side_effect = OSError("connection refused")
        transport.is_connected = False

        discovery = MagicMock()
        discovery.compute_path.return_value = Path("/tmp/svc.sock")

        spawner = MagicMock()
        spawner.spawn.side_effect = OSError("spawn failed")

        uc = _make_uc(transport=transport, discovery=discovery, spawner=spawner)

        # Act
        result = uc(**_make_call_kwargs())

        # Assert
        assert result == ClientState.DEGRADED

    def test_reconnect_after_spawn_still_fails_returns_degraded(self):
        """
        Given: initial connect fails, spawn succeeds, but post-spawn connect also fails
        When: ReconnectUseCase is called
        Then: returns ClientState.DEGRADED
        """
        # Arrange
        connect_call_count = [0]

        transport = MagicMock()
        transport.is_connected = False

        def connect_side_effect(path):
            connect_call_count[0] += 1
            raise OSError("connection refused")

        transport.connect.side_effect = connect_side_effect

        discovery = MagicMock()
        discovery.compute_path.return_value = Path("/tmp/svc.sock")

        spawner = MagicMock()
        spawner.spawn.return_value = 12345

        uc = _make_uc(transport=transport, discovery=discovery, spawner=spawner)

        # Act
        with patch("snitchbot.client.app.use_cases.reconnect_uc.flock_guard"):
            result = uc(**_make_call_kwargs())

        # Assert
        assert result == ClientState.DEGRADED


# ---------------------------------------------------------------------------
# ReconnectUseCase — never raises (invariant I7)
# ---------------------------------------------------------------------------


class TestReconnectNeverRaises:
    def test_reconnect_never_raises_on_internal_exception(self):
        """
        Given: transport.connect raises an unexpected exception (e.g. RuntimeError)
        When: ReconnectUseCase is called
        Then: no exception propagates — returns ClientState.DEGRADED
        """
        # Arrange
        transport = MagicMock()
        transport.connect.side_effect = RuntimeError("unexpected internal error")
        transport.is_connected = False

        discovery = MagicMock()
        discovery.compute_path.return_value = Path("/tmp/svc.sock")

        spawner = MagicMock()
        spawner.spawn.side_effect = RuntimeError("also broken")

        uc = _make_uc(transport=transport, discovery=discovery, spawner=spawner)

        # Act — must not raise
        result = uc(**_make_call_kwargs())

        # Assert
        assert result == ClientState.DEGRADED

    def test_reconnect_never_raises_on_discovery_exception(self):
        """
        Given: discovery.compute_path raises an unexpected exception
        When: ReconnectUseCase is called
        Then: no exception propagates — returns ClientState.DEGRADED
        """
        # Arrange
        discovery = MagicMock()
        discovery.compute_path.side_effect = RuntimeError("path computation failed")

        uc = _make_uc(discovery=discovery)

        # Act — must not raise
        result = uc(**_make_call_kwargs())

        # Assert
        assert result == ClientState.DEGRADED


# ---------------------------------------------------------------------------
# ReconnectUseCase — stats counter
# ---------------------------------------------------------------------------


class TestReconnectStats:
    def test_stats_incremented_on_failure(self):
        """
        Given: transport.connect fails and spawn also fails
        When: ReconnectUseCase is called
        Then: stats.sidecar_unavailable is incremented by 1
        """
        # Arrange
        transport = MagicMock()
        transport.connect.side_effect = OSError("connection refused")
        transport.is_connected = False

        discovery = MagicMock()
        discovery.compute_path.return_value = Path("/tmp/svc.sock")

        spawner = MagicMock()
        spawner.spawn.side_effect = OSError("spawn failed")

        stats = ClientStats()
        uc = _make_uc(transport=transport, discovery=discovery, spawner=spawner, stats=stats)

        # Act
        uc(**_make_call_kwargs())

        # Assert
        assert stats.sidecar_unavailable == 1

    def test_stats_not_incremented_on_success(self):
        """
        Given: transport.connect succeeds
        When: ReconnectUseCase is called
        Then: stats.sidecar_unavailable remains 0
        """
        # Arrange
        transport = MagicMock()
        transport.connect.return_value = None
        transport.is_connected = True

        discovery = MagicMock()
        discovery.compute_path.return_value = Path("/tmp/svc.sock")

        stats = ClientStats()
        uc = _make_uc(transport=transport, discovery=discovery, stats=stats)

        # Act
        uc(**_make_call_kwargs())

        # Assert
        assert stats.sidecar_unavailable == 0
