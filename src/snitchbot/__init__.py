from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__: str = _pkg_version("snitchbot")
except PackageNotFoundError:
    # Not installed (running from a source checkout without an install step).
    __version__ = "0.0.0+unknown"

# Public API re-exports
from snitchbot.client.adapters.driving.instrumentation.request_context import request_context
from snitchbot.client.adapters.driving.instrumentation.watch_slow import watch_slow
from snitchbot.client.ports.driving.public_api import init, notify
from snitchbot.shared.domain.anomaly_config_vo import (
    AnomalyConfig,
    CpuAnomalyConfig,
    CpuSustainedConfig,
    FdAnomalyConfig,
    FdLeakConfig,
    RssAnomalyConfig,
    RssSpikeConfig,
    ThreadAnomalyConfig,
    ThreadGrowthConfig,
    WatchdogConfig,
)


def setup_logging(*, level: int | None = None, logger_name: str = "") -> None:
    """Attach snitchbot handler to a stdlib logger. One-liner integration.

    Forwards WARNING+ log records to Telegram as custom notifications.
    Duplicate logs are deduplicated sidecar-side (shown as ``× N``).
    Automatically picks up ``request_context`` — logs inside a context
    block will include trace_id and extras in the alert.

    Args:
        level:       Minimum level (clamped to WARNING). Default: WARNING.
        logger_name: Logger name to attach to. Default: root logger ("").
    """
    import logging

    from snitchbot.integrations import SnitchbotLoggingHandler

    kwargs: dict = {}
    if level is not None:
        kwargs["level"] = level
    handler = SnitchbotLoggingHandler(**kwargs)
    logging.getLogger(logger_name).addHandler(handler)


def setup_structlog():
    """Return a structlog processor that forwards WARNING+ events to Telegram.

    For caller info (file, line, function) in alerts, add
    ``CallsiteParameterAdder`` before this processor::

        import structlog
        from structlog.processors import CallsiteParameterAdder, CallsiteParameter

        structlog.configure(processors=[
            structlog.stdlib.add_log_level,
            CallsiteParameterAdder([
                CallsiteParameter.PATHNAME,
                CallsiteParameter.LINENO,
                CallsiteParameter.FUNC_NAME,
            ]),
            snitchbot.setup_structlog(),
            structlog.dev.ConsoleRenderer(),
        ])

    Without ``CallsiteParameterAdder``, alerts will not show caller info.
    """
    from snitchbot.integrations import make_structlog_processor

    return make_structlog_processor()


__all__ = [
    "__version__",
    "init",
    "notify",
    "watch_slow",
    "request_context",
    "setup_logging",
    "setup_structlog",
    "AnomalyConfig",
    "RssAnomalyConfig",
    "CpuAnomalyConfig",
    "FdAnomalyConfig",
    "ThreadAnomalyConfig",
    "WatchdogConfig",
    "RssSpikeConfig",
    "CpuSustainedConfig",
    "FdLeakConfig",
    "ThreadGrowthConfig",
]
