"""Unit tests for window parser and command parsing — Tasks 9.2.

Spec: interactive §4.2, §5.2, §7.2, §8.2.
Invariants: none directly, but T9 relies on correct parse of fingerprint/duration.
"""
import pytest

from snitchbot.sidecar.interactive.domain.window_parser_vo import (
    parse_command_args,
    parse_window,
)

# ---------------------------------------------------------------------------
# test_parse_window_5m_1h_24h_7d_ok
# ---------------------------------------------------------------------------


def test_parse_window_5m_1h_24h_7d_ok():
    """
    Given canonical window strings,
    When parse_window() is called,
    Then the correct number of seconds is returned.
    """
    assert parse_window("5m") == 300
    assert parse_window("1h") == 3600
    assert parse_window("24h") == 86400
    assert parse_window("7d") == 7 * 86400


# ---------------------------------------------------------------------------
# test_parse_window_bad_format_raises
# ---------------------------------------------------------------------------


def test_parse_window_bad_format_raises():
    """
    Given strings with unsupported formats,
    When parse_window() is called,
    Then ValueError is raised for each.
    """
    bad = ["5min", "1 h", "1H", "1D", "abc", "", "0m", "-1h", "7d1h"]
    for s in bad:
        with pytest.raises(ValueError, match=r"(window|invalid|out of range)"):
            parse_window(s)


# ---------------------------------------------------------------------------
# test_parse_window_out_of_range_raises
# ---------------------------------------------------------------------------


def test_parse_window_out_of_range_raises():
    """
    Given window values outside bounds [1m, 30d],
    When parse_window() is called,
    Then ValueError is raised.
    """
    # too small: 0 minutes
    with pytest.raises(ValueError):
        parse_window("0m")
    # too large: 31 days
    with pytest.raises(ValueError):
        parse_window("31d")
    # edge valid
    assert parse_window("1m") == 60
    assert parse_window("30d") == 30 * 86400


# ---------------------------------------------------------------------------
# test_parse_status_args_ordering_free
# ---------------------------------------------------------------------------


def test_parse_status_args_ordering_free():
    """
    Given /status with or without a window arg,
    When parse_command_args() is called,
    Then window_sec is populated or defaults to 3600 (1h).
    """
    # No args — default 1h
    result = parse_command_args("/status", "status")
    assert result == {"window_sec": 3600}

    # Explicit window
    result = parse_command_args("/status 5m", "status")
    assert result == {"window_sec": 300}

    result = parse_command_args("/status 24h", "status")
    assert result == {"window_sec": 86400}


# ---------------------------------------------------------------------------
# test_parse_last_args_free_order_N_window_all
# ---------------------------------------------------------------------------


def test_parse_last_args_free_order_N_window_all():
    """
    Given /last with free-order args (N, window, all),
    When parse_command_args() is called,
    Then n, window_sec, and include_warnings are correctly extracted.
    """
    # defaults
    result = parse_command_args("/last", "last")
    assert result["n"] == 5
    assert result["window_sec"] == 3600
    assert result["include_warnings"] is False

    # explicit N
    result = parse_command_args("/last 10", "last")
    assert result["n"] == 10
    assert result["include_warnings"] is False

    # N + window
    result = parse_command_args("/last 20 24h", "last")
    assert result["n"] == 20
    assert result["window_sec"] == 86400

    # all
    result = parse_command_args("/last all", "last")
    assert result["include_warnings"] is True

    # free order: all first, then N and window
    result = parse_command_args("/last all 10 1h", "last")
    assert result["n"] == 10
    assert result["window_sec"] == 3600
    assert result["include_warnings"] is True


# ---------------------------------------------------------------------------
# test_parse_mute_requires_fp_and_duration
# ---------------------------------------------------------------------------


def test_parse_mute_requires_fp_and_duration():
    """
    Given /mute commands with and without required args,
    When parse_command_args() is called,
    Then fingerprint and duration are parsed, or ValueError raised.
    """
    # point mute
    result = parse_command_args("/mute a1b2c3 1h", "mute")
    assert result["fingerprint"] == "a1b2c3"
    assert result["duration_sec"] == 3600

    # global mute
    result = parse_command_args("/mute all 30m", "mute")
    assert result["fingerprint"] == "all"
    assert result["duration_sec"] == 1800

    # missing duration -> ValueError
    with pytest.raises(ValueError):
        parse_command_args("/mute a1b2c3", "mute")

    # missing both -> ValueError
    with pytest.raises(ValueError):
        parse_command_args("/mute", "mute")


# ---------------------------------------------------------------------------
# test_parse_unmute_accepts_fp_or_all
# ---------------------------------------------------------------------------


def test_parse_unmute_accepts_fp_or_all():
    """
    Given /unmute with fingerprint or 'all',
    When parse_command_args() is called,
    Then fingerprint field is set correctly.
    """
    result = parse_command_args("/unmute a1b2c3", "unmute")
    assert result["fingerprint"] == "a1b2c3"

    result = parse_command_args("/unmute all", "unmute")
    assert result["fingerprint"] == "all"

    # missing arg -> ValueError
    with pytest.raises(ValueError):
        parse_command_args("/unmute", "unmute")


# ---------------------------------------------------------------------------
# test_parse_last_n_capped_at_20
# ---------------------------------------------------------------------------


def test_parse_last_n_capped_at_20():
    """
    Given /last with N > 20,
    When parse_command_args() is called,
    Then n is clamped to 20 (spec §5.5: max N=20).
    """
    result = parse_command_args("/last 50", "last")
    assert result["n"] == 20
