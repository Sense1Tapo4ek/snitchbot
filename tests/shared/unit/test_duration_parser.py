"""Unit tests for parse_duration (anomaly config duration parser).

Pure domain: stdlib only, no mocks needed.
"""
from __future__ import annotations

import pytest

from snitchbot.shared.domain.services.window_parser_service import (
    WindowParseError,
    parse_duration,
)


class TestParseDurationStrings:
    def test_seconds(self):
        """
        Given "30s",
        When parse_duration is called,
        Then 30 is returned.
        """
        assert parse_duration("30s") == 30

    def test_minutes(self):
        """
        Given "2m",
        When parse_duration is called,
        Then 120 is returned.
        """
        assert parse_duration("2m") == 120

    def test_hours(self):
        """
        Given "1h",
        When parse_duration is called,
        Then 3600 is returned.
        """
        assert parse_duration("1h") == 3600

    def test_days(self):
        """
        Given "1d",
        When parse_duration is called,
        Then 86400 is returned.
        """
        assert parse_duration("1d") == 86400

    def test_2_days(self):
        """
        Given "2d",
        When parse_duration is called,
        Then 172800 is returned (max allowed).
        """
        assert parse_duration("2d") == 172800

    def test_48_hours(self):
        """
        Given "48h",
        When parse_duration is called,
        Then 172800 is returned.
        """
        assert parse_duration("48h") == 172800

    def test_whitespace_stripped(self):
        """
        Given " 5m ",
        When parse_duration is called,
        Then 300 is returned (whitespace stripped).
        """
        assert parse_duration(" 5m ") == 300


class TestParseDurationInt:
    def test_int_passthrough(self):
        """
        Given 120 (int),
        When parse_duration is called,
        Then 120 is returned unchanged.
        """
        assert parse_duration(120) == 120

    def test_int_one_second(self):
        """
        Given 1,
        When parse_duration is called,
        Then 1 is returned (minimum valid).
        """
        assert parse_duration(1) == 1

    def test_int_max(self):
        """
        Given 172800 (48h),
        When parse_duration is called,
        Then 172800 is returned (max valid).
        """
        assert parse_duration(172800) == 172800


class TestParseDurationEdgeCases:
    def test_zero_seconds_raises(self):
        """
        Given "0s",
        When parse_duration is called,
        Then WindowParseError is raised.
        """
        with pytest.raises(WindowParseError):
            parse_duration("0s")

    def test_zero_int_raises(self):
        """
        Given 0,
        When parse_duration is called,
        Then WindowParseError is raised.
        """
        with pytest.raises(WindowParseError):
            parse_duration(0)

    def test_negative_int_raises(self):
        """
        Given -1,
        When parse_duration is called,
        Then WindowParseError is raised.
        """
        with pytest.raises(WindowParseError):
            parse_duration(-1)

    def test_over_48h_string_raises(self):
        """
        Given "49h",
        When parse_duration is called,
        Then WindowParseError is raised (exceeds 48h cap).
        """
        with pytest.raises(WindowParseError):
            parse_duration("49h")

    def test_over_48h_int_raises(self):
        """
        Given 172801,
        When parse_duration is called,
        Then WindowParseError is raised.
        """
        with pytest.raises(WindowParseError):
            parse_duration(172801)

    def test_3d_raises(self):
        """
        Given "3d" (259200s > 172800),
        When parse_duration is called,
        Then WindowParseError is raised.
        """
        with pytest.raises(WindowParseError):
            parse_duration("3d")

    def test_empty_string_raises(self):
        """
        Given "",
        When parse_duration is called,
        Then WindowParseError is raised.
        """
        with pytest.raises(WindowParseError):
            parse_duration("")

    def test_bad_format_raises(self):
        """
        Given "abc",
        When parse_duration is called,
        Then WindowParseError is raised.
        """
        with pytest.raises(WindowParseError):
            parse_duration("abc")

    def test_missing_unit_raises(self):
        """
        Given "30",
        When parse_duration is called,
        Then WindowParseError is raised (no unit).
        """
        with pytest.raises(WindowParseError):
            parse_duration("30")


class TestParseDurationReturnType:
    def test_returns_int_from_string(self):
        """
        Given "5m",
        When parse_duration is called,
        Then result is int (not float).
        """
        result = parse_duration("5m")
        assert isinstance(result, int)

    def test_returns_int_from_int(self):
        """
        Given 60,
        When parse_duration is called,
        Then result is int.
        """
        result = parse_duration(60)
        assert isinstance(result, int)
