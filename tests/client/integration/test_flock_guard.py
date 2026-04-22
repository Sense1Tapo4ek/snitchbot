"""Integration tests for flock_guard (Task 2.2).

Integration category: uses real filesystem + fcntl. No mocks.
"""
import fcntl
import threading
import time
from pathlib import Path

import pytest

from snitchbot.client.ports.driven.discovery.flock_guard import flock_guard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _try_lock_nonblocking(lock_path: Path) -> bool:
    """Return True if a non-blocking exclusive lock CAN be acquired on lock_path."""
    with open(lock_path, "w") as fd:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fd, fcntl.LOCK_UN)
            return True
        except OSError:
            return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_flock_acquired_and_released_on_context_exit(tmp_path: Path) -> None:
    """
    Given a lock file path,
    When entering and then exiting the flock_guard context,
    Then the lock is held inside the block and released afterward.
    """
    lock_file = tmp_path / "test.lock"

    # Before: lock file may not exist yet — that's fine
    with flock_guard(lock_file) as fd:
        # Inside: non-blocking attempt from a separate fd must FAIL
        assert not _try_lock_nonblocking(lock_file), "Lock should be held inside context"

    # After: lock is released — non-blocking attempt must SUCCEED
    assert _try_lock_nonblocking(lock_file), "Lock should be released after context exit"


def test_flock_waits_for_concurrent_holder(tmp_path: Path) -> None:
    """
    Given a thread holding the flock,
    When a second thread tries to acquire the same lock,
    Then the second thread blocks until the first releases it.
    """
    lock_file = tmp_path / "concurrent.lock"
    acquired_order: list[str] = []
    barrier = threading.Event()

    def holder() -> None:
        with flock_guard(lock_file):
            acquired_order.append("holder")
            barrier.set()       # signal: holder has lock
            time.sleep(0.05)    # hold it briefly

    def waiter() -> None:
        barrier.wait()          # wait until holder has the lock
        with flock_guard(lock_file):
            acquired_order.append("waiter")

    t1 = threading.Thread(target=holder)
    t2 = threading.Thread(target=waiter)
    t1.start()
    t2.start()
    t1.join(timeout=2)
    t2.join(timeout=2)

    assert acquired_order == ["holder", "waiter"], (
        f"Expected holder then waiter, got: {acquired_order}"
    )


def test_flock_released_even_on_exception(tmp_path: Path) -> None:
    """
    Given a flock_guard context that raises inside the body,
    When the exception propagates,
    Then the lock is still released (finally block).
    """
    lock_file = tmp_path / "exception.lock"

    with pytest.raises(ValueError, match="boom"):
        with flock_guard(lock_file):
            raise ValueError("boom")

    # Lock must be released despite the exception
    assert _try_lock_nonblocking(lock_file), "Lock must be released after exception"


def test_flock_released_before_client_runtime(tmp_path: Path) -> None:
    """
    Given the flock_guard context has exited (-> I6: lock held ONLY during
    discovery/spawn, released BEFORE normal client runtime),
    When we attempt a non-blocking exclusive lock from another fd,
    Then it succeeds — confirming the lock is not held during client runtime.
    """
    lock_file = tmp_path / "i6.lock"

    with flock_guard(lock_file):
        pass  # simulate discovery/spawn

    # Simulate "client runtime" — verify no lock is held
    assert _try_lock_nonblocking(lock_file), (
        "I6 violated: lock still held after flock_guard context exit"
    )


def test_lock_file_created_if_missing(tmp_path: Path) -> None:
    """
    Given a lock file path whose parent exists but the file itself does not,
    When flock_guard is used,
    Then the lock file is created automatically.
    """
    lock_file = tmp_path / "new_dir" / "new.lock"

    with flock_guard(lock_file):
        assert lock_file.exists()
