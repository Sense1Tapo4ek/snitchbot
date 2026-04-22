"""Flow tests for InitializeClientUseCase (Task 2.6).

Tests cover:
- Optimistic connect succeeds -> flock never acquired -> CONNECTED (I6, §5.2.2)
- Optimistic connect fails -> flock path -> re-check -> spawn
- After flock, socket appeared (another process spawned) -> connect -> CONNECTED
- After flock, socket exists but connect fails -> unlink + spawn
- Spawn -> poll timeout -> DEGRADED (I2, I3)
- Handshake rejected -> DEGRADED (I8, §8.6)
- Handshake timeout -> DEGRADED (§8.5)
- Any unexpected exception inside -> returns DEGRADED (I9, P1)
- __call__ never raises -> always returns ClientState (P8)
- stats.internal_errors incremented when exception caught

All external deps mocked with unittest.mock.MagicMock / patch.
No real filesystem, no real sockets, no real flock.
"""
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from snitchbot.client.app.interfaces import IDiscovery, ISidecarSpawner, ITransport
from snitchbot.client.app.use_cases.initialize_client_uc import InitializeClientUseCase
from snitchbot.client.domain.client_state_agg import ClientState
from snitchbot.client.domain.stats_vo import ClientStats
from snitchbot.client.errors import HandshakeRejectedError, HandshakeTimeoutError
from snitchbot.shared.generics.errors import PortError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOCKET_PATH = Path("/tmp/mylib/test_service/test.sock")
_LOCK_PATH = _SOCKET_PATH.with_suffix(".lock")

_SERVICE = "test_service"
_TOKEN = "test_token"
_CHAT_ID = "123456"
_ANOMALY_CONFIG = None


def _make_uc(
    *,
    discovery: IDiscovery | None = None,
    transport: ITransport | None = None,
    spawner: ISidecarSpawner | None = None,
    stats: ClientStats | None = None,
) -> InitializeClientUseCase:
    """Create a UC with all mocks by default."""
    if discovery is None:
        discovery = MagicMock(spec=IDiscovery)
        discovery.compute_path.return_value = _SOCKET_PATH
    if transport is None:
        transport = MagicMock(spec=ITransport)
    if spawner is None:
        spawner = MagicMock(spec=ISidecarSpawner)
    if stats is None:
        stats = ClientStats()
    return InitializeClientUseCase(
        _discovery=discovery,
        _transport=transport,
        _spawner=spawner,
        _stats=stats,
    )


# ---------------------------------------------------------------------------
# Optimistic connect path
# ---------------------------------------------------------------------------


class TestOptimisticConnectSucceedsNoFlock:
    def test_optimistic_connect_succeeds_no_flock_acquired(self):
        """
        Given: transport.connect() succeeds on first call, handshake passes
        When: __call__ is invoked
        Then: returns CONNECTED and flock_guard is never entered (I6, §5.2.2)
        """
        # Arrange
        transport = MagicMock(spec=ITransport)
        # connect succeeds (no exception)
        uc = _make_uc(transport=transport)

        with patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.flock_guard"
        ) as mock_flock, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.perform_handshake"
        ) as mock_handshake:
            mock_handshake.return_value = {
                "type": "hello_ack",
                "sidecar_pid": 9999,
                "version": "0.1.0",
            }

            # Act
            result = uc(
                service=_SERVICE,
                token=_TOKEN,
                chat_id=_CHAT_ID,
                anomaly_config=_ANOMALY_CONFIG,
            )

        # Assert
        assert result == ClientState.CONNECTED
        mock_flock.assert_not_called()
        transport.connect.assert_called_once_with(_SOCKET_PATH)

    def test_optimistic_connect_transport_connect_called_with_computed_path(self):
        """
        Given: discovery returns a specific path
        When: __call__ is invoked and connect succeeds
        Then: transport.connect is called with exactly that path
        """
        # Arrange
        custom_path = Path("/tmp/custom/path.sock")
        discovery = MagicMock(spec=IDiscovery)
        discovery.compute_path.return_value = custom_path
        transport = MagicMock(spec=ITransport)
        uc = _make_uc(discovery=discovery, transport=transport)

        with patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.perform_handshake"
        ) as mock_handshake:
            mock_handshake.return_value = {"type": "hello_ack", "sidecar_pid": 1, "version": "0.1"}

            uc(service=_SERVICE, token=_TOKEN, chat_id=_CHAT_ID)

        # Assert
        transport.connect.assert_called_with(custom_path)


# ---------------------------------------------------------------------------
# Optimistic connect fails -> flock path
# ---------------------------------------------------------------------------


class TestOptimisticConnectFailsGoesToFlockPath:
    def test_optimistic_connect_fails_goes_to_flock_path(self):
        """
        Given: optimistic connect fails, socket absent under flock, spawn, poll succeeds
        When: __call__ is invoked
        Then: flock_guard is entered (slow path) and spawner is eventually invoked -> CONNECTED
        """
        # Arrange
        transport = MagicMock(spec=ITransport)
        # 1st: optimistic connect fails; 2nd: post-poll connect succeeds (no re-check since _path_exists=False)
        transport.connect.side_effect = [PortError("refused"), None]
        uc = _make_uc(transport=transport)

        with patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.flock_guard"
        ) as mock_flock, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._path_exists"
        ) as mock_exists, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._poll_socket"
        ) as mock_poll, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.perform_handshake"
        ) as mock_handshake:
            mock_exists.return_value = False  # socket not present under flock -> skip re-check
            mock_poll.return_value = True  # socket appears after spawn
            mock_handshake.return_value = {
                "type": "hello_ack",
                "sidecar_pid": 9999,
                "version": "0.1.0",
            }

            # Act
            result = uc(
                service=_SERVICE,
                token=_TOKEN,
                chat_id=_CHAT_ID,
                anomaly_config=_ANOMALY_CONFIG,
            )

        # Assert
        assert result == ClientState.CONNECTED
        mock_flock.assert_called_once_with(_LOCK_PATH)

    def test_flock_recheck_connects_if_socket_now_present(self):
        """
        Given: optimistic connect fails, but under flock socket now exists and connect succeeds
        When: __call__ is invoked
        Then: returns CONNECTED without spawning (§5.2 re-check path)
        """
        # Arrange
        transport = MagicMock(spec=ITransport)
        # First optimistic connect fails, then re-check connect succeeds
        transport.connect.side_effect = [PortError("refused"), None]
        spawner = MagicMock(spec=ISidecarSpawner)
        uc = _make_uc(transport=transport, spawner=spawner)

        with patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.flock_guard"
        ) as mock_flock, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._path_exists"
        ) as mock_exists, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.perform_handshake"
        ) as mock_handshake:
            mock_flock.return_value.__enter__ = MagicMock(return_value=None)
            mock_flock.return_value.__exit__ = MagicMock(return_value=False)
            mock_exists.return_value = True  # socket exists under flock re-check
            mock_handshake.return_value = {"type": "hello_ack", "sidecar_pid": 9999, "version": "0.1.0"}

            # Act
            result = uc(
                service=_SERVICE,
                token=_TOKEN,
                chat_id=_CHAT_ID,
                anomaly_config=_ANOMALY_CONFIG,
            )

        # Assert
        assert result == ClientState.CONNECTED
        spawner.spawn.assert_not_called()

    def test_flock_recheck_stale_unlinks_and_spawns(self):
        """
        Given: optimistic connect fails, under flock socket exists but connect fails (stale)
        When: __call__ is invoked
        Then: socket is unlinked and spawner is called
        """
        # Arrange
        transport = MagicMock(spec=ITransport)
        # 1st: optimistic fails; 2nd: re-check stale fails; 3rd: post-poll succeeds
        transport.connect.side_effect = [PortError("refused"), PortError("refused"), None]
        spawner = MagicMock(spec=ISidecarSpawner)
        uc = _make_uc(transport=transport, spawner=spawner)

        with patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.flock_guard"
        ) as mock_flock, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._path_exists"
        ) as mock_exists, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._unlink_path"
        ) as mock_unlink, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._poll_socket"
        ) as mock_poll, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.perform_handshake"
        ) as mock_handshake:
            mock_flock.return_value.__enter__ = MagicMock(return_value=None)
            mock_flock.return_value.__exit__ = MagicMock(return_value=False)
            mock_exists.return_value = True   # socket exists (stale)
            mock_poll.return_value = True     # poll succeeds after spawn
            mock_handshake.return_value = {"type": "hello_ack", "sidecar_pid": 9999, "version": "0.1.0"}

            # Act
            result = uc(
                service=_SERVICE,
                token=_TOKEN,
                chat_id=_CHAT_ID,
                anomaly_config=_ANOMALY_CONFIG,
            )

        # Assert
        mock_unlink.assert_called_once_with(_SOCKET_PATH)
        spawner.spawn.assert_called_once()
        assert result == ClientState.CONNECTED


# ---------------------------------------------------------------------------
# Spawn -> poll timeout -> DEGRADED
# ---------------------------------------------------------------------------


class TestSpawnThenPollTimeout:
    def test_spawn_then_poll_timeout_transitions_to_degraded(self):
        """
        Given: spawner.spawn() succeeds but socket never appears within poll timeout
        When: __call__ is invoked
        Then: returns DEGRADED without raising (I2, I3)
        """
        # Arrange
        transport = MagicMock(spec=ITransport)
        transport.connect.side_effect = PortError("refused")
        spawner = MagicMock(spec=ISidecarSpawner)
        uc = _make_uc(transport=transport, spawner=spawner)

        with patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.flock_guard"
        ) as mock_flock, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._path_exists"
        ) as mock_exists, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._unlink_path"
        ), patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._poll_socket"
        ) as mock_poll:
            mock_flock.return_value.__enter__ = MagicMock(return_value=None)
            mock_flock.return_value.__exit__ = MagicMock(return_value=False)
            mock_exists.return_value = False  # socket absent under flock
            mock_poll.return_value = False    # poll timeout — socket never appears

            # Act
            result = uc(
                service=_SERVICE,
                token=_TOKEN,
                chat_id=_CHAT_ID,
                anomaly_config=_ANOMALY_CONFIG,
            )

        # Assert
        assert result == ClientState.DEGRADED
        spawner.spawn.assert_called_once()


# ---------------------------------------------------------------------------
# Handshake failures -> DEGRADED
# ---------------------------------------------------------------------------


class TestHandshakeFailuresTransitionToDegraded:
    def test_handshake_rejected_transitions_to_degraded(self):
        """
        Given: connect succeeds but handshake raises HandshakeRejectedError
        When: __call__ is invoked
        Then: returns DEGRADED without raising (I8, §8.6)
        """
        # Arrange
        transport = MagicMock(spec=ITransport)
        uc = _make_uc(transport=transport)

        with patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.flock_guard"
        ) as mock_flock, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.perform_handshake"
        ) as mock_handshake:
            mock_flock.return_value.__enter__ = MagicMock(return_value=None)
            mock_flock.return_value.__exit__ = MagicMock(return_value=False)
            mock_handshake.side_effect = HandshakeRejectedError("config_hash_mismatch")

            # Act
            result = uc(
                service=_SERVICE,
                token=_TOKEN,
                chat_id=_CHAT_ID,
                anomaly_config=_ANOMALY_CONFIG,
            )

        # Assert
        assert result == ClientState.DEGRADED

    def test_handshake_timeout_transitions_to_degraded(self):
        """
        Given: connect succeeds but handshake raises HandshakeTimeoutError
        When: __call__ is invoked
        Then: returns DEGRADED without raising (§8.5)
        """
        # Arrange
        transport = MagicMock(spec=ITransport)
        uc = _make_uc(transport=transport)

        with patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.flock_guard"
        ) as mock_flock, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.perform_handshake"
        ) as mock_handshake:
            mock_flock.return_value.__enter__ = MagicMock(return_value=None)
            mock_flock.return_value.__exit__ = MagicMock(return_value=False)
            mock_handshake.side_effect = HandshakeTimeoutError("no ack within 500ms")

            # Act
            result = uc(
                service=_SERVICE,
                token=_TOKEN,
                chat_id=_CHAT_ID,
                anomaly_config=_ANOMALY_CONFIG,
            )

        # Assert
        assert result == ClientState.DEGRADED


# ---------------------------------------------------------------------------
# Bug containment: never raises
# ---------------------------------------------------------------------------


class TestBugContainment:
    def test_bug_in_lib_does_not_raise_to_user(self):
        """
        Given: an unexpected exception occurs inside the UC (e.g., AttributeError)
        When: __call__ is invoked
        Then: exception is caught and DEGRADED is returned — never propagates (I9, P1)
        """
        # Arrange
        transport = MagicMock(spec=ITransport)
        transport.connect.side_effect = AttributeError("unexpected bug")
        uc = _make_uc(transport=transport)

        # Act — must not raise
        result = uc(
            service=_SERVICE,
            token=_TOKEN,
            chat_id=_CHAT_ID,
            anomaly_config=_ANOMALY_CONFIG,
        )

        # Assert
        assert result == ClientState.DEGRADED

    def test_init_never_raises(self):
        """
        Given: discovery.compute_path raises a RuntimeError
        When: __call__ is invoked
        Then: no exception escapes, returns DEGRADED (P8)
        """
        # Arrange
        discovery = MagicMock(spec=IDiscovery)
        discovery.compute_path.side_effect = RuntimeError("catastrophic failure")
        uc = _make_uc(discovery=discovery)

        # Act — must not raise
        result = uc(
            service=_SERVICE,
            token=_TOKEN,
            chat_id=_CHAT_ID,
            anomaly_config=_ANOMALY_CONFIG,
        )

        # Assert
        assert result == ClientState.DEGRADED

    def test_stats_incremented_on_internal_error(self):
        """
        Given: an unexpected exception occurs inside the UC
        When: __call__ is invoked
        Then: stats.internal_errors is incremented by 1
        """
        # Arrange
        transport = MagicMock(spec=ITransport)
        transport.connect.side_effect = RuntimeError("unexpected")
        stats = ClientStats()
        uc = _make_uc(transport=transport, stats=stats)

        assert stats.internal_errors == 0

        # Act
        uc(
            service=_SERVICE,
            token=_TOKEN,
            chat_id=_CHAT_ID,
            anomaly_config=_ANOMALY_CONFIG,
        )

        # Assert
        assert stats.internal_errors == 1

    def test_stats_not_incremented_on_expected_degraded_path(self):
        """
        Given: poll timeout leads to degraded (no unexpected exception)
        When: __call__ is invoked
        Then: stats.internal_errors is NOT incremented (only truly unexpected exceptions count)
        """
        # Arrange
        transport = MagicMock(spec=ITransport)
        transport.connect.side_effect = PortError("refused")
        stats = ClientStats()
        spawner = MagicMock(spec=ISidecarSpawner)
        uc = _make_uc(transport=transport, spawner=spawner, stats=stats)

        with patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.flock_guard"
        ) as mock_flock, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._path_exists"
        ) as mock_exists, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._unlink_path"
        ), patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._poll_socket"
        ) as mock_poll:
            mock_flock.return_value.__enter__ = MagicMock(return_value=None)
            mock_flock.return_value.__exit__ = MagicMock(return_value=False)
            mock_exists.return_value = False
            mock_poll.return_value = False  # poll timeout

            uc(service=_SERVICE, token=_TOKEN, chat_id=_CHAT_ID)

        # Assert
        assert stats.internal_errors == 0


# ---------------------------------------------------------------------------
# Spawner is called with correct arguments
# ---------------------------------------------------------------------------


class TestSpawnerCalledWithCorrectArgs:
    def test_spawner_receives_correct_service_token_chat_id_socket_path(self):
        """
        Given: optimistic connect fails, no socket under flock, poll succeeds
        When: __call__ is invoked
        Then: spawner.spawn receives correct keyword arguments
        """
        # Arrange
        transport = MagicMock(spec=ITransport)
        transport.connect.side_effect = PortError("refused")
        spawner = MagicMock(spec=ISidecarSpawner)
        uc = _make_uc(transport=transport, spawner=spawner)

        with patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.flock_guard"
        ) as mock_flock, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._path_exists"
        ) as mock_exists, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._unlink_path"
        ), patch(
            "snitchbot.client.app.use_cases.initialize_client_uc._poll_socket"
        ) as mock_poll, patch(
            "snitchbot.client.app.use_cases.initialize_client_uc.perform_handshake"
        ) as mock_handshake:
            mock_flock.return_value.__enter__ = MagicMock(return_value=None)
            mock_flock.return_value.__exit__ = MagicMock(return_value=False)
            mock_exists.return_value = False
            mock_poll.return_value = True
            mock_handshake.return_value = {"type": "hello_ack", "sidecar_pid": 1, "version": "0.1"}

            uc(service=_SERVICE, token=_TOKEN, chat_id=_CHAT_ID)

        # Assert
        spawner.spawn.assert_called_once_with(
            service=_SERVICE,
            token=_TOKEN,
            chat_id=_CHAT_ID,
            socket_path=_SOCKET_PATH,
            log_path=None,
        )
