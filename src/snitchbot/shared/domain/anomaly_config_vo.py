"""Anomaly detection config value objects — v2 unified 3-mode model.

Public API (re-exported from ``snitchbot``) — see public-api §3.5 and
live-message-vitals §4.5–4.6.

All classes are frozen dataclasses (stdlib only, slots, kw_only). Validation
happens in ``__post_init__`` and raises
:class:`InvalidAnomalyConfigError` (invariant A8).

v2 changes from v1:
- Unified 3-mode detection per metric: ceiling, spike, drop.
- Time-based windows (``duration`` / ``baseline_duration``) instead of sample counts.
- ``WatchdogConfig`` with multi-threshold severity.
- Renamed: rss_spike -> memory, cpu_sustained -> cpu, fd_leak -> fds, thread_growth -> threads.
"""

import dataclasses
from dataclasses import dataclass, field

from .errors import InvalidAnomalyConfigError
from .services.window_parser_service import WindowParseError, parse_duration


@dataclass(frozen=True, slots=True, kw_only=True)
class RssAnomalyConfig:
    """Config for memory (RSS) anomaly detector.

    3 detection modes:
    - **Ceiling**: ``max_mb`` — hard RSS limit, severity ``error``.
    - **Spike**: ``spike_ratio`` + ``min_spike_mb`` — relative growth, severity ``warning``.
    - **Drop**: ``drop_ratio`` + ``min_drop_mb`` — relative decline, severity ``warning``.

    Set any mode to ``None`` to disable it.
    """

    duration: str | int = "1m"
    baseline_duration: str | int = "30m"
    max_mb: float | None = 450.0
    spike_ratio: float | None = 1.5
    min_spike_mb: float | None = 50.0
    drop_ratio: float | None = None
    min_drop_mb: float | None = None

    def __post_init__(self) -> None:
        _validate_durations(self.duration, self.baseline_duration, "rss")
        if self.max_mb is not None and self.max_mb <= 0:
            raise InvalidAnomalyConfigError(
                f"rss.max_mb must be > 0, got {self.max_mb!r}"
            )
        _validate_ratio(self.spike_ratio, "rss.spike_ratio")
        _validate_positive_or_none(self.min_spike_mb, "rss.min_spike_mb")
        _validate_drop_ratio(self.drop_ratio, "rss.drop_ratio")
        _validate_positive_or_none(self.min_drop_mb, "rss.min_drop_mb")

    @property
    def duration_sec(self) -> int:
        return parse_duration(self.duration)

    @property
    def baseline_duration_sec(self) -> int:
        return parse_duration(self.baseline_duration)


@dataclass(frozen=True, slots=True, kw_only=True)
class CpuAnomalyConfig:
    """Config for CPU anomaly detector.

    3 detection modes:
    - **Ceiling**: ``max_percent`` — hard CPU% limit, severity ``error``.
    - **Spike**: ``spike_ratio`` + ``min_spike_delta`` — relative growth, severity ``warning``.
    - **Drop**: ``drop_ratio`` + ``min_drop_delta`` — CPU starvation, severity ``warning``.

    Set any mode to ``None`` to disable it.
    """

    duration: str | int = "2m"
    baseline_duration: str | int = "20m"
    max_percent: float | None = 90.0
    spike_ratio: float | None = 2.5
    min_spike_delta: float | None = 30.0
    drop_ratio: float | None = None
    min_drop_delta: float | None = None

    def __post_init__(self) -> None:
        _validate_durations(self.duration, self.baseline_duration, "cpu")
        if self.max_percent is not None and not (0 < self.max_percent <= 100):
            raise InvalidAnomalyConfigError(
                f"cpu.max_percent must be in (0, 100], got {self.max_percent!r}"
            )
        _validate_ratio(self.spike_ratio, "cpu.spike_ratio")
        _validate_positive_or_none(self.min_spike_delta, "cpu.min_spike_delta")
        _validate_drop_ratio(self.drop_ratio, "cpu.drop_ratio")
        _validate_positive_or_none(self.min_drop_delta, "cpu.min_drop_delta")

    @property
    def duration_sec(self) -> int:
        return parse_duration(self.duration)

    @property
    def baseline_duration_sec(self) -> int:
        return parse_duration(self.baseline_duration)


@dataclass(frozen=True, slots=True, kw_only=True)
class FdAnomalyConfig:
    """Config for file descriptor anomaly detector.

    3 detection modes:
    - **Ceiling**: ``max_fds`` — hard FD limit (ulimit protection), severity ``error``.
    - **Spike**: ``spike_ratio`` + ``min_spike_delta`` — FD leak detection, severity ``error``.
    - **Drop**: ``drop_ratio`` + ``min_drop_delta`` — pool collapse, severity ``warning``.

    Set any mode to ``None`` to disable it.
    """

    duration: str | int = "5m"
    baseline_duration: str | int = "1h"
    max_fds: int | None = 800
    spike_ratio: float | None = 1.5
    min_spike_delta: int | None = 50
    drop_ratio: float | None = 0.5
    min_drop_delta: int | None = 50

    def __post_init__(self) -> None:
        _validate_durations(self.duration, self.baseline_duration, "fds")
        if self.max_fds is not None and self.max_fds <= 0:
            raise InvalidAnomalyConfigError(
                f"fds.max_fds must be > 0, got {self.max_fds!r}"
            )
        _validate_ratio(self.spike_ratio, "fds.spike_ratio")
        _validate_positive_int_or_none(self.min_spike_delta, "fds.min_spike_delta")
        _validate_drop_ratio(self.drop_ratio, "fds.drop_ratio")
        _validate_positive_int_or_none(self.min_drop_delta, "fds.min_drop_delta")

    @property
    def duration_sec(self) -> int:
        return parse_duration(self.duration)

    @property
    def baseline_duration_sec(self) -> int:
        return parse_duration(self.baseline_duration)


@dataclass(frozen=True, slots=True, kw_only=True)
class ThreadAnomalyConfig:
    """Config for thread count anomaly detector.

    3 detection modes:
    - **Ceiling**: ``max_threads`` — hard thread limit, severity ``error``.
    - **Spike**: ``spike_ratio`` + ``min_spike_delta`` — thread leak, severity ``warning``.
    - **Drop**: ``drop_ratio`` + ``min_drop_delta`` — worker collapse, severity ``warning``.

    Set any mode to ``None`` to disable it.
    """

    duration: str | int = "1m"
    baseline_duration: str | int = "15m"
    max_threads: int | None = 100
    spike_ratio: float | None = 1.5
    min_spike_delta: int | None = 10
    drop_ratio: float | None = 0.5
    min_drop_delta: int | None = 5

    def __post_init__(self) -> None:
        _validate_durations(self.duration, self.baseline_duration, "threads")
        if self.max_threads is not None and self.max_threads <= 0:
            raise InvalidAnomalyConfigError(
                f"threads.max_threads must be > 0, got {self.max_threads!r}"
            )
        _validate_ratio(self.spike_ratio, "threads.spike_ratio")
        _validate_positive_int_or_none(self.min_spike_delta, "threads.min_spike_delta")
        _validate_drop_ratio(self.drop_ratio, "threads.drop_ratio")
        _validate_positive_int_or_none(self.min_drop_delta, "threads.min_drop_delta")

    @property
    def duration_sec(self) -> int:
        return parse_duration(self.duration)

    @property
    def baseline_duration_sec(self) -> int:
        return parse_duration(self.baseline_duration)


@dataclass(frozen=True, slots=True, kw_only=True)
class WatchdogConfig:
    """Config for asyncio event loop watchdog.

    Multi-threshold severity:
    - ``threshold_ms`` — minimum block duration to trigger (severity ``warning``).
    - ``error_threshold_ms`` — block duration for severity ``error``.
    - ``critical_threshold_ms`` — block duration for severity ``critical``.

    Escalation window: repeated hits within ``escalation_window`` escalate severity.
    """

    enabled: bool = True
    threshold_ms: int = 500
    error_threshold_ms: int | None = 2000
    critical_threshold_ms: int | None = 5000
    cooldown_sec: int = 10
    escalation_window: str | int = "1m"

    def __post_init__(self) -> None:
        if self.threshold_ms <= 0:
            raise InvalidAnomalyConfigError(
                f"watchdog.threshold_ms must be > 0, got {self.threshold_ms!r}"
            )
        if self.error_threshold_ms is not None:
            if self.error_threshold_ms <= self.threshold_ms:
                raise InvalidAnomalyConfigError(
                    f"watchdog.error_threshold_ms ({self.error_threshold_ms}) "
                    f"must be > threshold_ms ({self.threshold_ms})"
                )
        if self.critical_threshold_ms is not None:
            floor = self.error_threshold_ms or self.threshold_ms
            if self.critical_threshold_ms <= floor:
                raise InvalidAnomalyConfigError(
                    f"watchdog.critical_threshold_ms ({self.critical_threshold_ms}) "
                    f"must be > {floor}"
                )
        if self.cooldown_sec < 0:
            raise InvalidAnomalyConfigError(
                f"watchdog.cooldown_sec must be >= 0, got {self.cooldown_sec!r}"
            )
        try:
            parse_duration(self.escalation_window)
        except WindowParseError as e:
            raise InvalidAnomalyConfigError(
                f"watchdog.escalation_window: {e}"
            ) from e

    @property
    def escalation_window_sec(self) -> int:
        return parse_duration(self.escalation_window)


_DETECTOR_FIELDS: tuple[str, ...] = (
    "rss",
    "cpu",
    "fds",
    "threads",
    "watchdog",
)

_FIELD_TO_CLASS: dict[str, type] = {
    "rss": RssAnomalyConfig,
    "cpu": CpuAnomalyConfig,
    "fds": FdAnomalyConfig,
    "threads": ThreadAnomalyConfig,
    "watchdog": WatchdogConfig,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class AnomalyConfig:
    """Top-level per-client anomaly-detection config.

    All detectors default to their spec-default instances (enabled).
    Setting any slot to ``None`` disables ONLY that detector.

    To disable every detector, use :meth:`AnomalyConfig.all_disabled`.
    """

    rss: RssAnomalyConfig | None = field(default_factory=RssAnomalyConfig)
    cpu: CpuAnomalyConfig | None = field(default_factory=CpuAnomalyConfig)
    fds: FdAnomalyConfig | None = field(default_factory=FdAnomalyConfig)
    threads: ThreadAnomalyConfig | None = field(default_factory=ThreadAnomalyConfig)
    watchdog: WatchdogConfig | None = field(default_factory=WatchdogConfig)

    @classmethod
    def defaults(cls) -> "AnomalyConfig":
        """Return an AnomalyConfig with all detectors at spec defaults."""
        return cls()

    @classmethod
    def all_disabled(cls) -> "AnomalyConfig":
        """Return an AnomalyConfig with every detector explicitly disabled."""
        return cls(
            rss=None,
            cpu=None,
            fds=None,
            threads=None,
            watchdog=None,
        )

    @classmethod
    def from_dict(cls, data: dict | None) -> "AnomalyConfig":
        """Parse a canonical wire-format dict back into an AnomalyConfig VO.

        Inverse of :meth:`resolve`. Used by the sidecar on hello handshake.

        - ``None`` or empty dict -> defaults (all enabled).
        - Missing detector key -> spec default for that detector.
        - Detector value ``None`` -> detector disabled.
        - Detector value dict -> construct the corresponding config VO.
        """
        if not data:
            return cls.defaults()

        def _build(field_name: str) -> object:
            config_cls = _FIELD_TO_CLASS[field_name]
            if field_name not in data:
                return config_cls()  # default
            value = data[field_name]
            if value is None:
                return None
            if isinstance(value, dict):
                # Filter out computed properties and duration_sec fields
                valid_keys = {f.name for f in dataclasses.fields(config_cls)}
                filtered = {k: v for k, v in value.items() if k in valid_keys}
                return config_cls(**filtered)
            return config_cls()

        return cls(
            rss=_build("rss"),
            cpu=_build("cpu"),
            fds=_build("fds"),
            threads=_build("threads"),
            watchdog=_build("watchdog"),
        )

    def resolve(self) -> dict:
        """Return the canonical wire-format dict.

        Keys are always present and in stable order. Values are plain
        primitive dicts (msgpack-friendly) when the detector is enabled, or
        ``None`` when disabled.
        """
        resolved: dict = {}
        for field_name in _DETECTOR_FIELDS:
            value = getattr(self, field_name)
            resolved[field_name] = (
                dataclasses.asdict(value) if value is not None else None
            )
        return resolved

    def max_history_seconds(self) -> int:
        """Compute the longest baseline_duration across all enabled detectors.

        Used by the sidecar to size the per-client vitals history deque.
        """
        max_sec = 300  # minimum 5 minutes
        for field_name in ("rss", "cpu", "fds", "threads"):
            cfg = getattr(self, field_name)
            if cfg is not None:
                max_sec = max(max_sec, cfg.baseline_duration_sec)
        return max_sec


AnomalyParam = AnomalyConfig | bool | None


def resolve_anomaly_param(param: AnomalyParam) -> AnomalyConfig:
    """Resolve the ``init(anomaly=...)`` user input to an :class:`AnomalyConfig`.

    - ``None`` -> defaults (all detectors enabled).
    - ``True`` -> defaults (all detectors enabled).
    - ``False`` -> every detector disabled.
    - :class:`AnomalyConfig` instance -> returned as-is.
    """
    if param is False:
        return AnomalyConfig.all_disabled()
    if param is None or param is True:
        return AnomalyConfig.defaults()
    if isinstance(param, AnomalyConfig):
        return param
    raise InvalidAnomalyConfigError(
        f"anomaly must be None, bool, or AnomalyConfig, got {type(param).__name__}"
    )


MemoryAnomalyConfig = RssAnomalyConfig  # renamed in v2.1
RssSpikeConfig = RssAnomalyConfig
CpuSustainedConfig = CpuAnomalyConfig
FdLeakConfig = FdAnomalyConfig
ThreadGrowthConfig = ThreadAnomalyConfig


def _validate_durations(
    duration: str | int, baseline_duration: str | int, prefix: str,
) -> None:
    """Validate that both durations parse and baseline >= duration."""
    try:
        dur_sec = parse_duration(duration)
    except WindowParseError as e:
        raise InvalidAnomalyConfigError(f"{prefix}.duration: {e}") from e
    try:
        base_sec = parse_duration(baseline_duration)
    except WindowParseError as e:
        raise InvalidAnomalyConfigError(
            f"{prefix}.baseline_duration: {e}"
        ) from e
    if base_sec < dur_sec:
        raise InvalidAnomalyConfigError(
            f"{prefix}.baseline_duration ({baseline_duration}) "
            f"must be >= duration ({duration})"
        )


def _validate_ratio(value: float | None, name: str) -> None:
    if value is not None and (value <= 0 or value > 100):
        raise InvalidAnomalyConfigError(
            f"{name} must be in (0, 100], got {value!r}"
        )


def _validate_drop_ratio(value: float | None, name: str) -> None:
    if value is not None and (value <= 0 or value >= 1):
        raise InvalidAnomalyConfigError(
            f"{name} must be in (0, 1), got {value!r}"
        )


def _validate_positive_or_none(value: float | None, name: str) -> None:
    if value is not None and value < 0:
        raise InvalidAnomalyConfigError(
            f"{name} must be >= 0, got {value!r}"
        )


def _validate_positive_int_or_none(value: int | None, name: str) -> None:
    if value is not None and value < 0:
        raise InvalidAnomalyConfigError(
            f"{name} must be >= 0, got {value!r}"
        )
