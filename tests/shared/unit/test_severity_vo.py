"""Unit tests for Severity VO and severity_rank helper."""
from typing import get_args

import pytest

from snitchbot.shared.domain import (
    InvalidSeverityError,
    Severity,
    severity_rank,
)
from snitchbot.shared.generics.errors import DomainError


class TestSeverityLiterals:
    def test_severity_literal_values_warning_error_critical(self) -> None:
        """
        Given the Severity Literal type,
        When inspecting its type args,
        Then it contains exactly warning, error, critical.
        """
        assert set(get_args(Severity)) == {"warning", "error", "critical"}


class TestSeverityRank:
    def test_severity_rank_ordering(self) -> None:
        """
        Given each severity level,
        When computing its rank,
        Then warning < error < critical with ranks 1, 2, 3.
        """
        assert severity_rank("warning") == 1
        assert severity_rank("error") == 2
        assert severity_rank("critical") == 3
        assert severity_rank("warning") < severity_rank("error") < severity_rank("critical")

    @pytest.mark.parametrize("bad", ["debug", "foo", "", "WARNING", "Error"])
    def test_severity_rank_unknown_raises(self, bad: str) -> None:
        """
        Given an unknown severity string,
        When calling severity_rank,
        Then InvalidSeverityError is raised.
        """
        with pytest.raises(InvalidSeverityError):
            severity_rank(bad)  # type: ignore[arg-type]


class TestInvalidSeverityError:
    def test_invalid_severity_is_domain_error(self) -> None:
        """
        Given InvalidSeverityError,
        When checking its hierarchy,
        Then it is a subclass of DomainError.
        """
        assert issubclass(InvalidSeverityError, DomainError)
