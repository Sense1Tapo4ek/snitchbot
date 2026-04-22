"""Flock guard context manager (Task 2.2).

Wraps ``fcntl.flock(LOCK_EX)`` to prevent races during sidecar discovery/spawn.

Per spec §5.2 and invariant I6:
- The lock is held ONLY during discovery/spawn.
- It MUST be released BEFORE normal client runtime.
"""
import fcntl
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

__all__ = ["flock_guard"]


@contextmanager
def flock_guard(lock_path: Path) -> Generator[IO[str], None, None]:
    """Acquire an exclusive ``flock`` on *lock_path*, yield, release on exit.

    Creates the lock file (and any missing parent directories) if they do not
    exist.  The lock is always released in the ``finally`` block, so it is
    safe to raise inside the ``with`` body.

    Args:
        lock_path: Path to the lock file.  Will be created if absent.

    Yields:
        The open file descriptor for the lock file.

    Example::

        with flock_guard(tmp_path / "sidecar.lock"):
            pid = spawn_sidecar()
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = open(lock_path, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield fd
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
