"""Unit tests for anomaly config VOs — v2 unified 3-mode model.

Validates:
- All 5 config types construct with defaults
- Duration parsing in __post_init__
- Threshold validation (ceiling, spike, drop fields)
- None disables detector
- AnomalyConfig.defaults() / all_disabled()
- resolve() -> from_dict() round-trip
- max_history_seconds() computation
- WatchdogConfig threshold ordering
- Immutability (frozen)
- Deprecated v1 aliases
"""

import dataclasses

import pytest

from snitchbot.shared.domain import (
    AnomalyConfig,
    CpuAnomalyConfig,
    FdAnomalyConfig,
    InvalidAnomalyConfigError,
    RssAnomalyConfig,
    ThreadAnomalyConfig,
    WatchdogConfig,
)
from snitchbot.shared.domain.anomaly_config_vo import (
    CpuSustainedConfig,
    FdLeakConfig,
    RssSpikeConfig,
    ThreadGrowthConfig,
    resolve_anomaly_param,
)
from snitchbot.shared.generics.errors import DomainError


CANONICAL_KEYS = ("rss", "cpu", "fds", "threads", "watchdog", "total_rss", "total_cpu")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_defaults_produce_all_five_enabled(self):
        """
        Given AnomalyConfig.defaults(),
        When resolved to the canonical dict,
        Then the five base slots are non-None and total_* are None.
        """
        resolved = AnomalyConfig.defaults().resolve()
        assert set(resolved.keys()) == set(CANONICAL_KEYS)
        for key in ("rss", "cpu", "fds", "threads", "watchdog"):
            assert resolved[key] is not None, f"detector {key} must be enabled by default"
        assert resolved["total_rss"] is None
        assert resolved["total_cpu"] is None

    def test_none_produces_defaults(self):
        """
        Given user_input=None,
        When resolve_anomaly_param is called,
        Then result equals AnomalyConfig.defaults().
        """
        assert resolve_anomaly_param(None) == AnomalyConfig.defaults()

    def test_true_produces_defaults(self):
        """
        Given user_input=True,
        When resolve_anomaly_param is called,
        Then result equals AnomalyConfig.defaults().
        """
        assert resolve_anomaly_param(True) == AnomalyConfig.defaults()


# ---------------------------------------------------------------------------
# All disabled
# ---------------------------------------------------------------------------


class TestAllDisabled:
    def test_false_produces_all_disabled(self):
        """
        Given user_input=False,
        When resolve_anomaly_param().resolve() is called,
        Then all keys are None.
        """
        resolved = resolve_anomaly_param(False).resolve()
        assert set(resolved.keys()) == set(CANONICAL_KEYS)
        for key in CANONICAL_KEYS:
            assert resolved[key] is None

    def test_all_disabled_classmethod(self):
        """
        Given AnomalyConfig.all_disabled(),
        When inspecting its fields,
        Then every slot is None.
        """
        cfg = AnomalyConfig.all_disabled()
        assert cfg.rss is None
        assert cfg.cpu is None
        assert cfg.fds is None
        assert cfg.threads is None
        assert cfg.watchdog is None
        assert cfg.total_rss is None
        assert cfg.total_cpu is None


# ---------------------------------------------------------------------------
# Partial override
# ---------------------------------------------------------------------------


class TestPartialOverride:
    def test_override_one_detector(self):
        """
        Given AnomalyConfig with ONLY memory explicitly set,
        When resolved,
        Then memory uses override AND others have defaults.
        """
        cfg = AnomalyConfig(rss=RssAnomalyConfig(max_mb=200.0))
        resolved = cfg.resolve()
        assert resolved["rss"] is not None
        assert resolved["rss"]["max_mb"] == 200.0
        assert resolved["cpu"] is not None
        assert resolved["fds"] is not None
        assert resolved["threads"] is not None
        assert resolved["watchdog"] is not None
        assert resolved["total_rss"] is None
        assert resolved["total_cpu"] is None

    def test_disable_one_detector_via_none(self):
        """
        Given AnomalyConfig with fds=None,
        When resolved,
        Then fds is None AND others remain enabled.
        """
        cfg = AnomalyConfig(fds=None)
        resolved = cfg.resolve()
        assert resolved["fds"] is None
        assert resolved["rss"] is not None
        assert resolved["cpu"] is not None
        assert resolved["threads"] is not None
        assert resolved["total_rss"] is None
        assert resolved["total_cpu"] is None

    def test_resolve_anomaly_param_passes_instance_through(self):
        """
        Given an AnomalyConfig instance,
        When passed to resolve_anomaly_param,
        Then the same instance is returned.
        """
        cfg = AnomalyConfig(rss=RssAnomalyConfig(max_mb=200.0))
        assert resolve_anomaly_param(cfg) is cfg


# ---------------------------------------------------------------------------
# Duration parsing
# ---------------------------------------------------------------------------


class TestDurationParsing:
    def test_memory_duration_sec_property(self):
        """
        Given RssAnomalyConfig with duration="2m",
        When accessing duration_sec,
        Then 120 is returned.
        """
        cfg = RssAnomalyConfig(duration="2m")
        assert cfg.duration_sec == 120

    def test_cpu_baseline_duration_sec(self):
        """
        Given CpuAnomalyConfig with baseline_duration="1h",
        When accessing baseline_duration_sec,
        Then 3600 is returned.
        """
        cfg = CpuAnomalyConfig(baseline_duration="1h")
        assert cfg.baseline_duration_sec == 3600

    def test_int_duration_passthrough(self):
        """
        Given RssAnomalyConfig with duration=90 (int),
        When accessing duration_sec,
        Then 90 is returned.
        """
        cfg = RssAnomalyConfig(duration=90, baseline_duration=1800)
        assert cfg.duration_sec == 90

    def test_invalid_duration_raises(self):
        """
        Given an invalid duration string,
        When constructing a config,
        Then InvalidAnomalyConfigError is raised.
        """
        with pytest.raises(InvalidAnomalyConfigError):
            RssAnomalyConfig(duration="abc")

    def test_baseline_smaller_than_duration_raises(self):
        """
        Given baseline_duration < duration,
        When constructing a config,
        Then InvalidAnomalyConfigError is raised.
        """
        with pytest.raises(InvalidAnomalyConfigError):
            RssAnomalyConfig(duration="10m", baseline_duration="5m")


# ---------------------------------------------------------------------------
# Memory validation
# ---------------------------------------------------------------------------


class TestMemoryValidation:
    def test_max_mb_zero_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            RssAnomalyConfig(max_mb=0.0)

    def test_max_mb_negative_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            RssAnomalyConfig(max_mb=-1.0)

    def test_spike_ratio_zero_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            RssAnomalyConfig(spike_ratio=0.0)

    def test_spike_ratio_over_100_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            RssAnomalyConfig(spike_ratio=101.0)

    def test_drop_ratio_zero_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            RssAnomalyConfig(drop_ratio=0.0)

    def test_drop_ratio_1_raises(self):
        """drop_ratio must be < 1 (it's a fraction, e.g. 0.5 = 50% drop)."""
        with pytest.raises(InvalidAnomalyConfigError):
            RssAnomalyConfig(drop_ratio=1.0)

    def test_min_spike_mb_negative_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            RssAnomalyConfig(min_spike_mb=-1.0)

    def test_all_modes_none_is_valid(self):
        """All detection modes disabled — still a valid config."""
        cfg = RssAnomalyConfig(
            max_mb=None, spike_ratio=None, min_spike_mb=None,
            drop_ratio=None, min_drop_mb=None,
        )
        assert cfg.max_mb is None
        assert cfg.spike_ratio is None
        assert cfg.drop_ratio is None


# ---------------------------------------------------------------------------
# CPU validation
# ---------------------------------------------------------------------------


class TestCpuValidation:
    def test_max_percent_over_100_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            CpuAnomalyConfig(max_percent=101.0)

    def test_max_percent_zero_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            CpuAnomalyConfig(max_percent=0.0)


# ---------------------------------------------------------------------------
# FD validation
# ---------------------------------------------------------------------------


class TestFdValidation:
    def test_max_fds_zero_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            FdAnomalyConfig(max_fds=0)

    def test_min_spike_delta_negative_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            FdAnomalyConfig(min_spike_delta=-1)


# ---------------------------------------------------------------------------
# Thread validation
# ---------------------------------------------------------------------------


class TestThreadValidation:
    def test_max_threads_zero_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            ThreadAnomalyConfig(max_threads=0)

    def test_max_threads_negative_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            ThreadAnomalyConfig(max_threads=-1)


# ---------------------------------------------------------------------------
# Watchdog validation
# ---------------------------------------------------------------------------


class TestWatchdogValidation:
    def test_threshold_ms_zero_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            WatchdogConfig(threshold_ms=0)

    def test_error_threshold_must_exceed_threshold(self):
        with pytest.raises(InvalidAnomalyConfigError):
            WatchdogConfig(threshold_ms=500, error_threshold_ms=500)

    def test_error_threshold_below_threshold_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            WatchdogConfig(threshold_ms=500, error_threshold_ms=400)

    def test_critical_must_exceed_error(self):
        with pytest.raises(InvalidAnomalyConfigError):
            WatchdogConfig(
                threshold_ms=500,
                error_threshold_ms=1000,
                critical_threshold_ms=1000,
            )

    def test_critical_must_exceed_threshold_when_error_none(self):
        with pytest.raises(InvalidAnomalyConfigError):
            WatchdogConfig(
                threshold_ms=500,
                error_threshold_ms=None,
                critical_threshold_ms=500,
            )

    def test_valid_monotonic_thresholds(self):
        """
        Given monotonically increasing thresholds,
        When constructing WatchdogConfig,
        Then no error is raised.
        """
        cfg = WatchdogConfig(
            threshold_ms=200,
            error_threshold_ms=800,
            critical_threshold_ms=1500,
        )
        assert cfg.threshold_ms == 200
        assert cfg.error_threshold_ms == 800
        assert cfg.critical_threshold_ms == 1500

    def test_escalation_window_sec_property(self):
        cfg = WatchdogConfig(escalation_window="2m")
        assert cfg.escalation_window_sec == 120

    def test_invalid_escalation_window_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            WatchdogConfig(escalation_window="abc")

    def test_cooldown_negative_raises(self):
        with pytest.raises(InvalidAnomalyConfigError):
            WatchdogConfig(cooldown_sec=-1)


# ---------------------------------------------------------------------------
# max_history_seconds
# ---------------------------------------------------------------------------


class TestMaxHistorySeconds:
    def test_defaults_returns_longest_baseline(self):
        """
        Given default config (memory=30m, cpu=20m, fds=1h, threads=15m),
        When max_history_seconds() is called,
        Then 3600 (1h from fds) is returned.
        """
        cfg = AnomalyConfig.defaults()
        assert cfg.max_history_seconds() == 3600

    def test_custom_longer_baseline(self):
        """
        Given memory with baseline_duration="2h" (7200s),
        When max_history_seconds() is called,
        Then 7200 is returned.
        """
        cfg = AnomalyConfig(
            rss=RssAnomalyConfig(baseline_duration="2h"),
        )
        assert cfg.max_history_seconds() == 7200

    def test_all_disabled_returns_minimum(self):
        """
        Given all detectors disabled,
        When max_history_seconds() is called,
        Then minimum 300 (5 min) is returned.
        """
        cfg = AnomalyConfig.all_disabled()
        assert cfg.max_history_seconds() == 300


# ---------------------------------------------------------------------------
# Resolve / from_dict round-trip
# ---------------------------------------------------------------------------


class TestResolveRoundTrip:
    def test_resolve_from_dict_roundtrip(self):
        """
        Given a custom AnomalyConfig,
        When resolve() -> from_dict() round-trip,
        Then the result equals the original.
        """
        original = AnomalyConfig(
            rss=RssAnomalyConfig(max_mb=200.0, spike_ratio=2.0),
            cpu=CpuAnomalyConfig(max_percent=85.0),
            fds=None,
            threads=ThreadAnomalyConfig(max_threads=50),
            watchdog=WatchdogConfig(threshold_ms=300, error_threshold_ms=1000),
            total_rss=None,
            total_cpu=None,
        )
        wire = original.resolve()
        restored = AnomalyConfig.from_dict(wire)
        assert restored == original

    def test_from_dict_none_returns_defaults(self):
        assert AnomalyConfig.from_dict(None) == AnomalyConfig.defaults()

    def test_from_dict_empty_returns_defaults(self):
        assert AnomalyConfig.from_dict({}) == AnomalyConfig.defaults()

    def test_from_dict_missing_key_uses_default(self):
        """Missing key -> default for that detector, not None."""
        wire = {"rss": None}  # only memory specified as disabled
        cfg = AnomalyConfig.from_dict(wire)
        assert cfg.rss is None
        assert cfg.cpu is not None  # default, not None
        assert cfg.fds is not None
        assert cfg.total_rss is None
        assert cfg.total_cpu is None

    def test_resolved_dict_is_plain(self):
        """Canonical form is msgpack-friendly — no dataclass instances."""
        resolved = AnomalyConfig.defaults().resolve()
        for value in resolved.values():
            assert not dataclasses.is_dataclass(value)


# ---------------------------------------------------------------------------
# Canonical shape
# ---------------------------------------------------------------------------


class TestCanonicalShape:
    def test_all_keys_present_in_order(self):
        resolved = AnomalyConfig.defaults().resolve()
        assert list(resolved.keys()) == list(CANONICAL_KEYS)

    def test_all_disabled_has_all_keys(self):
        resolved = AnomalyConfig.all_disabled().resolve()
        assert list(resolved.keys()) == list(CANONICAL_KEYS)

    def test_values_are_dict_or_none(self):
        resolved = AnomalyConfig.defaults().resolve()
        for key in CANONICAL_KEYS:
            value = resolved[key]
            assert value is None or isinstance(value, dict)


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestImmutability:
    def test_memory_config_is_frozen(self):
        cfg = RssAnomalyConfig()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.max_mb = 999.0  # type: ignore[misc]

    def test_anomaly_config_is_frozen(self):
        cfg = AnomalyConfig.defaults()
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.rss = None  # type: ignore[misc]

    def test_rejects_unknown_kwargs(self):
        with pytest.raises(TypeError):
            AnomalyConfig(foo=1)  # type: ignore[call-arg]

    def test_memory_rejects_unknown_kwargs(self):
        with pytest.raises(TypeError):
            RssAnomalyConfig(bogus=1)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    def test_invalid_anomaly_config_error_is_domain_error(self):
        assert issubclass(InvalidAnomalyConfigError, DomainError)

    def test_invalid_anomaly_config_error_is_not_dataclass(self):
        assert not dataclasses.is_dataclass(InvalidAnomalyConfigError)


# ---------------------------------------------------------------------------
# Deprecated v1 aliases
# ---------------------------------------------------------------------------


class TestDeprecatedAliases:
    def test_rss_spike_config_is_memory(self):
        assert RssSpikeConfig is RssAnomalyConfig

    def test_cpu_sustained_config_is_cpu(self):
        assert CpuSustainedConfig is CpuAnomalyConfig

    def test_fd_leak_config_is_fds(self):
        assert FdLeakConfig is FdAnomalyConfig

    def test_thread_growth_config_is_threads(self):
        assert ThreadGrowthConfig is ThreadAnomalyConfig
