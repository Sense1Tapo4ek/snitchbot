"""Task 14.4: Architecture static assertions.

Meta-tests that verify structural invariants of the codebase without
executing any production logic. All checks use pathlib + plain string
search — no AST required.
"""


import dataclasses
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SRC = Path(__file__).parent.parent / "src" / "snitchbot"
_CLIENT_SRC = _SRC / "client"
_SIDECAR_SRC = _SRC / "sidecar"
_ANOMALY_DETECTION_DIR = (
    _SIDECAR_SRC / "anomalies" / "domain" / "services"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _py_files(root: Path) -> list[Path]:
    """Return all .py files under *root* recursively."""
    return list(root.rglob("*.py"))


def _contains_pattern(path: Path, *patterns: str) -> bool:
    """Return True if the file text contains ANY of the given patterns."""
    text = path.read_text(encoding="utf-8")
    return any(p in text for p in patterns)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_anomaly_config_has_exactly_5_fields() -> None:
    """AnomalyConfig must have exactly 5 fields: memory, cpu, fds, threads, watchdog."""
    from snitchbot.shared.domain.anomaly_config_vo import AnomalyConfig

    field_names = {f.name for f in dataclasses.fields(AnomalyConfig)}
    expected = {"rss", "cpu", "fds", "threads", "watchdog"}

    assert field_names == expected, (
        f"AnomalyConfig fields mismatch.\n"
        f"  Expected : {sorted(expected)}\n"
        f"  Actual   : {sorted(field_names)}"
    )


def test_no_client_imports_psutil() -> None:
    """No file under src/mylib/client/ may import psutil."""
    offenders = [
        p
        for p in _py_files(_CLIENT_SRC)
        if _contains_pattern(p, "import psutil", "from psutil")
    ]
    assert not offenders, (
        "psutil imports found in client layer (must be sidecar-only):\n"
        + "\n".join(f"  {p}" for p in offenders)
    )


def test_no_client_imports_httpx() -> None:
    """No file under src/mylib/client/ may import httpx."""
    offenders = [
        p
        for p in _py_files(_CLIENT_SRC)
        if _contains_pattern(p, "import httpx", "from httpx")
    ]
    assert not offenders, (
        "httpx imports found in client layer (must be sidecar-only):\n"
        + "\n".join(f"  {p}" for p in offenders)
    )


def test_no_sidecar_uses_sys_getframe() -> None:
    """No file under src/mylib/sidecar/ may use sys._getframe.

    _getframe is a CPython implementation detail reserved for the client's
    hot path (stack extraction). Using it in the sidecar would be a layering
    violation and is architecturally unsound.
    """
    offenders = [
        p
        for p in _py_files(_SIDECAR_SRC)
        if _contains_pattern(p, "sys._getframe")
    ]
    assert not offenders, (
        "sys._getframe usage found in sidecar layer:\n"
        + "\n".join(f"  {p}" for p in offenders)
    )


def test_anomaly_detection_has_v2_detector_services() -> None:
    """anomaly_detection/ must contain the 4 v2 metric services + 2 shared services."""
    service_files = {f.name for f in _ANOMALY_DETECTION_DIR.glob("*_service.py")}
    required_v2 = {
        "rss_service.py", "cpu_service.py", "fds_service.py", "threads_service.py",
        "window_avg_service.py", "detection_modes_service.py",
    }
    assert required_v2.issubset(service_files), (
        f"Missing v2 service files: {required_v2 - service_files}"
    )
