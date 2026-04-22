"""Spawns the sidecar as a fully detached subprocess.

Implements ISidecarSpawner protocol.
"""

import os
import subprocess
import sys
from pathlib import Path

from snitchbot.client.errors import SpawnFailedError


class SubprocessSidecarSpawner:
    """Spawn sidecar as a detached subprocess. Implements ISidecarSpawner."""

    def spawn(
        self,
        *,
        service: str,
        token: str,
        chat_id: str | int,
        socket_path: Path,
        log_path: Path | None,
    ) -> int:
        env = {
            **os.environ,
            "SNITCHBOT_SIDECAR_SERVICE": service,
            "SNITCHBOT_TOKEN": token,
            "SNITCHBOT_CHAT_ID": str(chat_id),
            "SNITCHBOT_SIDECAR_SOCKET": str(socket_path),
        }

        # Allow env-based override for debugging (SNITCHBOT_SIDECAR_LOG)
        effective_log = log_path
        if effective_log is None:
            env_log = os.environ.get("SNITCHBOT_SIDECAR_LOG")
            if env_log:
                effective_log = Path(env_log)
                env["SNITCHBOT_DEBUG"] = "1"

        stderr_target = open(effective_log, "a") if effective_log else subprocess.DEVNULL

        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "snitchbot.sidecar"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_target,
                start_new_session=True,
                close_fds=True,
                env=env,
            )
        except OSError as exc:
            raise SpawnFailedError(f"Failed to spawn sidecar: {exc}") from exc
        finally:
            if log_path and stderr_target is not subprocess.DEVNULL:
                stderr_target.close()

        return proc.pid
