"""Test that `python -m snitchbot.sidecar` starts, binds socket, accepts hello, shuts down."""
import os
import signal
import socket
import subprocess
import sys
import time

import msgpack
import pytest

from snitchbot.shared.domain.services.config_hash_service import compute_config_hash


@pytest.fixture
def sidecar_process(tmp_path):
    """Start a real sidecar subprocess, yield its info, kill on cleanup."""
    sock_path = tmp_path / "test.sock"
    token = "test-token-123"
    chat_id = "12345"
    service = "test-svc"

    env = {
        **os.environ,
        "SNITCHBOT_SIDECAR_SOCKET": str(sock_path),
        "SNITCHBOT_SIDECAR_SERVICE": service,
        "SNITCHBOT_TOKEN": token,
        "SNITCHBOT_CHAT_ID": chat_id,
    }

    proc = subprocess.Popen(
        [sys.executable, "-m", "snitchbot.sidecar"],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Wait for socket to appear
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if sock_path.exists():
            break
        time.sleep(0.05)

    yield {
        "proc": proc,
        "sock_path": sock_path,
        "token": token,
        "chat_id": chat_id,
        "service": service,
        "config_hash": compute_config_hash(token, chat_id),
    }

    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=5)


class TestSidecarEntrypoint:
    def test_socket_created_on_start(self, sidecar_process):
        """
        Given a sidecar started with correct env,
        When the process is running,
        Then the UNIX socket file exists.
        """
        assert sidecar_process["sock_path"].exists()

    def test_hello_returns_ack(self, sidecar_process):
        """
        Given a running sidecar,
        When a client sends a hello with correct config_hash,
        Then the sidecar replies with hello_ack.
        """
        info = sidecar_process
        client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        client.bind("")  # autobind
        client.connect(str(info["sock_path"]))

        hello = msgpack.packb({
            "type": "hello",
            "pid": os.getpid(),
            "service": info["service"],
            "config_hash": info["config_hash"],
            "started_at": time.time(),
            "anomaly_config": None,
        })
        client.send(hello)

        client.settimeout(2.0)
        data = client.recv(65536)
        ack = msgpack.unpackb(data, raw=False)

        assert ack["type"] == "hello_ack"
        assert "sidecar_pid" in ack
        client.close()

    def test_sigterm_clean_shutdown(self, sidecar_process):
        """
        Given a running sidecar,
        When SIGTERM is sent,
        Then process exits with code 0 and socket file is removed.
        """
        proc = sidecar_process["proc"]
        sock_path = sidecar_process["sock_path"]

        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=5)

        assert code == 0
        assert not sock_path.exists()
