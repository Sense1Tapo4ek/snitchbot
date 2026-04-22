"""Kind-specific payload value objects for the snitchbot event envelope.

Also see ``docs/superpowers/specs/2026-04-11-logging-integration-design.md``
invariant L6 for ``CustomPayload.source``.

All payloads are frozen + slots + kw_only dataclasses. They are pure data —
validation is performed by the validation service in Task 1.4.
"""
from .anomaly_payload_vo import AnomalyPayload
from .crash_payload_vo import CrashPayload, StackFrame
from .custom_payload_vo import Caller, CustomPayload
from .lifecycle_payload_vo import LifecyclePayload
from .slow_call_payload_vo import Location, SlowCallPayload
from .watchdog_payload_vo import StuckTask, WatchdogPayload

__all__ = [
    "AnomalyPayload",
    "Caller",
    "CrashPayload",
    "CustomPayload",
    "LifecyclePayload",
    "Location",
    "SlowCallPayload",
    "StackFrame",
    "StuckTask",
    "WatchdogPayload",
]
