"""
Phase 0 scaffold tests — verify project structure, Python version gate, and extras.
These run RED first, then GREEN after implementation.
"""
import sys


def test_python_version():
    """Spec: Python >=3.10 required."""
    assert sys.version_info >= (3, 10), f"Got {sys.version_info}"


def test_package_importable():
    """All top-level subpackages must import without error."""
    import snitchbot  # noqa: F401
    import snitchbot.shared  # noqa: F401
    import snitchbot.client  # noqa: F401
    import snitchbot.sidecar  # noqa: F401
    import snitchbot.integrations  # noqa: F401
    import snitchbot.root  # noqa: F401


def test_py_typed_marker_present():
    """PEP 561 marker must exist so type checkers recognize the package."""
    import importlib.resources as ir
    # py.typed is a zero-byte marker; just check it exists
    ref = ir.files("snitchbot").joinpath("py.typed")
    assert ref.is_file(), "mylib/py.typed marker not found"


def test_msgpack_base_dep():
    """msgpack is a base dep — always importable."""
    import msgpack  # noqa: F401
