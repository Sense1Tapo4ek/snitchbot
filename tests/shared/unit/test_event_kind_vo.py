"""Unit tests for EventKind enum."""
from snitchbot.shared.domain import KINDS_WITH_SEVERITY, EventKind


class TestEventKindMembers:
    def test_six_kinds_exist(self) -> None:
        """
        Given EventKind,
        When enumerating members,
        Then there are exactly 6.
        """
        assert len(list(EventKind)) == 6

    def test_kind_values(self) -> None:
        """
        Given each EventKind member,
        When reading its value,
        Then it matches the lowercase kind string.
        """
        assert EventKind.CRASH.value == "crash"
        assert EventKind.CUSTOM.value == "custom"
        assert EventKind.SLOW_CALL.value == "slow_call"
        assert EventKind.WATCHDOG.value == "watchdog"
        assert EventKind.ANOMALY.value == "anomaly"
        assert EventKind.LIFECYCLE.value == "lifecycle"


class TestEventKindStringEnum:
    def test_event_kind_is_string_enum(self) -> None:
        """
        Given EventKind members,
        When comparing with raw strings,
        Then equality holds (StrEnum / str-mixed Enum behavior).
        """
        assert EventKind.CRASH == "crash"
        assert EventKind.LIFECYCLE == "lifecycle"


class TestKindsWithSeverity:
    def test_kinds_with_severity_excludes_lifecycle(self) -> None:
        """
        Given KINDS_WITH_SEVERITY,
        When checking membership,
        Then LIFECYCLE is excluded and all other five are included.
        """
        assert EventKind.LIFECYCLE not in KINDS_WITH_SEVERITY
        for kind in (
            EventKind.CRASH,
            EventKind.CUSTOM,
            EventKind.SLOW_CALL,
            EventKind.WATCHDOG,
            EventKind.ANOMALY,
        ):
            assert kind in KINDS_WITH_SEVERITY
        assert len(KINDS_WITH_SEVERITY) == 5
