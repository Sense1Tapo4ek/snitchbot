"""Task 14.1: Packaging sanity tests.

Verifies that pyproject.toml declares the correct Python requirement,
extras, and base dependencies — without importing the package build tools.
"""


import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent
_PYPROJECT = _ROOT / "pyproject.toml"


def _load_pyproject() -> dict:
    """Load pyproject.toml using tomllib (3.11+) or tomli fallback."""
    try:
        import tomllib  # type: ignore[import]
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[import,no-redef]

    with _PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


# Cache once per session — the file won't change during a test run.
_pyproject: dict = _load_pyproject()
_project: dict = _pyproject["project"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_python_requires_3_10() -> None:
    """requires-python must declare >=3.10."""
    requires = _project["requires-python"]
    assert ">=3.10" in requires, (
        f"requires-python should declare >=3.10, got {requires!r}"
    )


def test_base_deps_include_psutil_httpx() -> None:
    """psutil and httpx must be in base [project.dependencies]."""
    base_deps: list[str] = _project.get("dependencies", [])
    dep_names = {dep.split(">=")[0].split("==")[0].split(">")[0].strip().lower() for dep in base_deps}

    assert "psutil" in dep_names, f"psutil not found in base deps: {base_deps!r}"
    assert "httpx" in dep_names, f"httpx not found in base deps: {base_deps!r}"


def test_examples_extra_declares_frameworks() -> None:
    """[project.optional-dependencies.examples] must include fastapi, litestar, flask."""
    extras: dict[str, list[str]] = _project.get("optional-dependencies", {})
    examples_deps = extras.get("examples", [])
    dep_names = {dep.split(">=")[0].split("==")[0].split(">")[0].strip().lower() for dep in examples_deps}

    assert "fastapi" in dep_names, f"fastapi not in examples extras: {examples_deps!r}"
    assert "litestar" in dep_names, f"litestar not in examples extras: {examples_deps!r}"
    assert "flask" in dep_names, f"flask not in examples extras: {examples_deps!r}"


def test_msgpack_is_base_dep() -> None:
    """msgpack must be listed in base [project.dependencies]."""
    base_deps: list[str] = _project.get("dependencies", [])
    dep_names = {dep.split(">=")[0].split("==")[0].split(">")[0].strip().lower() for dep in base_deps}

    assert "msgpack" in dep_names, (
        f"msgpack not found in base dependencies: {base_deps!r}"
    )
