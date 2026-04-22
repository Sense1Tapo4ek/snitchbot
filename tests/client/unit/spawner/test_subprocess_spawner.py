"""Unit tests for SubprocessSidecarSpawner.

All subprocess.Popen calls are mocked — no real processes are spawned.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from snitchbot.client.app.interfaces.i_spawner import ISidecarSpawner
from snitchbot.client.errors import SpawnFailedError
from snitchbot.client.ports.driven.spawner.subprocess_spawner import SubprocessSidecarSpawner


@pytest.fixture
def spawner() -> SubprocessSidecarSpawner:
    return SubprocessSidecarSpawner()


@pytest.fixture
def mock_proc() -> MagicMock:
    proc = MagicMock()
    proc.pid = 12345
    return proc


@pytest.fixture
def socket_path(tmp_path: Path) -> Path:
    return tmp_path / "sidecar.sock"


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "sidecar.log"


class TestSpawnPOpenFlags:
    def test_spawn_uses_start_new_session_true(
        self, spawner: SubprocessSidecarSpawner, mock_proc: MagicMock, socket_path: Path
    ):
        """
        Given a spawner instance,
        When spawn() is called,
        Then Popen is invoked with start_new_session=True.
        """
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            spawner.spawn(
                service="telegram",
                token="tok",
                chat_id="123",
                socket_path=socket_path,
                log_path=None,
            )
            _, kwargs = mock_popen.call_args
            assert kwargs["start_new_session"] is True

    def test_spawn_closes_fds(
        self, spawner: SubprocessSidecarSpawner, mock_proc: MagicMock, socket_path: Path
    ):
        """
        Given a spawner instance,
        When spawn() is called,
        Then Popen is invoked with close_fds=True.
        """
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            spawner.spawn(
                service="telegram",
                token="tok",
                chat_id="123",
                socket_path=socket_path,
                log_path=None,
            )
            _, kwargs = mock_popen.call_args
            assert kwargs["close_fds"] is True

    def test_spawn_stdin_stdout_devnull(
        self, spawner: SubprocessSidecarSpawner, mock_proc: MagicMock, socket_path: Path
    ):
        """
        Given a spawner instance,
        When spawn() is called,
        Then Popen is invoked with stdin=DEVNULL and stdout=DEVNULL.
        """
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            spawner.spawn(
                service="telegram",
                token="tok",
                chat_id="123",
                socket_path=socket_path,
                log_path=None,
            )
            _, kwargs = mock_popen.call_args
            assert kwargs["stdin"] == subprocess.DEVNULL
            assert kwargs["stdout"] == subprocess.DEVNULL


class TestSpawnStderr:
    def test_spawn_stderr_redirected_to_log_file(
        self,
        spawner: SubprocessSidecarSpawner,
        mock_proc: MagicMock,
        socket_path: Path,
        log_path: Path,
    ):
        """
        Given a log_path is provided,
        When spawn() is called,
        Then Popen's stderr is a file object opened at log_path.
        """
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            with patch("builtins.open", create=True) as mock_open:
                fake_file = MagicMock()
                mock_open.return_value = fake_file

                spawner.spawn(
                    service="telegram",
                    token="tok",
                    chat_id="123",
                    socket_path=socket_path,
                    log_path=log_path,
                )

                mock_open.assert_called_once_with(log_path, "a")
                _, kwargs = mock_popen.call_args
                assert kwargs["stderr"] == fake_file

    def test_spawn_without_log_path_uses_devnull(
        self, spawner: SubprocessSidecarSpawner, mock_proc: MagicMock, socket_path: Path
    ):
        """
        Given log_path=None,
        When spawn() is called,
        Then Popen's stderr is subprocess.DEVNULL.
        """
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            spawner.spawn(
                service="telegram",
                token="tok",
                chat_id="123",
                socket_path=socket_path,
                log_path=None,
            )
            _, kwargs = mock_popen.call_args
            assert kwargs["stderr"] == subprocess.DEVNULL


class TestSpawnEnvironment:
    def test_spawn_env_contains_required_vars(
        self, spawner: SubprocessSidecarSpawner, mock_proc: MagicMock, socket_path: Path
    ):
        """
        Given spawn() is called with service, token, chat_id, socket_path,
        When Popen is invoked,
        Then the env dict contains all required SNITCHBOT_ vars.
        """
        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            spawner.spawn(
                service="telegram",
                token="secret-token",
                chat_id=42,
                socket_path=socket_path,
                log_path=None,
            )
            _, kwargs = mock_popen.call_args
            env = kwargs["env"]
            assert env["SNITCHBOT_SIDECAR_SERVICE"] == "telegram"
            assert env["SNITCHBOT_TOKEN"] == "secret-token"
            assert env["SNITCHBOT_CHAT_ID"] == "42"
            assert env["SNITCHBOT_SIDECAR_SOCKET"] == str(socket_path)

    def test_spawn_env_inherits_os_environ(
        self, spawner: SubprocessSidecarSpawner, mock_proc: MagicMock, socket_path: Path
    ):
        """
        Given the current process has environment variables,
        When spawn() is called,
        Then the env passed to Popen includes os.environ keys.
        """
        import os

        with patch("subprocess.Popen", return_value=mock_proc) as mock_popen:
            with patch.dict("os.environ", {"EXISTING_VAR": "existing_value"}):
                spawner.spawn(
                    service="telegram",
                    token="tok",
                    chat_id="123",
                    socket_path=socket_path,
                    log_path=None,
                )
                _, kwargs = mock_popen.call_args
                env = kwargs["env"]
                assert env["EXISTING_VAR"] == "existing_value"


class TestSpawnReturnValue:
    def test_spawn_returns_pid(
        self, spawner: SubprocessSidecarSpawner, mock_proc: MagicMock, socket_path: Path
    ):
        """
        Given Popen returns a process with pid=12345,
        When spawn() is called,
        Then it returns 12345.
        """
        mock_proc.pid = 12345
        with patch("subprocess.Popen", return_value=mock_proc):
            pid = spawner.spawn(
                service="telegram",
                token="tok",
                chat_id="123",
                socket_path=socket_path,
                log_path=None,
            )
            assert pid == 12345

    def test_spawn_returns_quickly_does_not_wait(
        self, spawner: SubprocessSidecarSpawner, mock_proc: MagicMock, socket_path: Path
    ):
        """
        Given spawn() is called,
        When Popen is invoked,
        Then proc.wait() is never called (fire-and-forget).
        """
        with patch("subprocess.Popen", return_value=mock_proc):
            spawner.spawn(
                service="telegram",
                token="tok",
                chat_id="123",
                socket_path=socket_path,
                log_path=None,
            )
            mock_proc.wait.assert_not_called()
            mock_proc.communicate.assert_not_called()


class TestSpawnErrorHandling:
    def test_spawn_failure_raises_spawn_failed_error(
        self, spawner: SubprocessSidecarSpawner, socket_path: Path
    ):
        """
        Given Popen raises an OSError,
        When spawn() is called,
        Then SpawnFailedError is raised.
        """
        with patch("subprocess.Popen", side_effect=OSError("exec failed")):
            with pytest.raises(SpawnFailedError):
                spawner.spawn(
                    service="telegram",
                    token="tok",
                    chat_id="123",
                    socket_path=socket_path,
                    log_path=None,
                )

    def test_spawn_failure_wraps_original_error(
        self, spawner: SubprocessSidecarSpawner, socket_path: Path
    ):
        """
        Given Popen raises an OSError,
        When spawn() is called,
        Then SpawnFailedError chains the original exception via __cause__.
        """
        original = OSError("exec failed")
        with patch("subprocess.Popen", side_effect=original):
            with pytest.raises(SpawnFailedError) as exc_info:
                spawner.spawn(
                    service="telegram",
                    token="tok",
                    chat_id="123",
                    socket_path=socket_path,
                    log_path=None,
                )
            assert exc_info.value.__cause__ is original


class TestSpawnProtocolCompliance:
    def test_spawn_implements_i_spawner_protocol(self, spawner: SubprocessSidecarSpawner):
        """
        Given SubprocessSidecarSpawner,
        When checked against ISidecarSpawner Protocol,
        Then isinstance returns True (runtime_checkable).
        """
        assert isinstance(spawner, ISidecarSpawner)
