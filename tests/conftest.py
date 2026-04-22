"""Global fixtures shared across all test contexts."""
import pytest


@pytest.fixture
def tmp_socket_path(tmp_path):
    """Return a tmp_path-based socket path that doesn't exist yet."""
    return tmp_path / "test.sock"
