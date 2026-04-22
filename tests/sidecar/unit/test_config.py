"""Unit tests for SnitchbotConfig (unified pydantic-settings based)."""
import pytest
from pydantic import ValidationError

from snitchbot.config import SnitchbotConfig


REQUIRED = {
    "SNITCHBOT_SIDECAR_SOCKET": "/tmp/test.sock",
    "SNITCHBOT_SIDECAR_SERVICE": "test-service",
    "SNITCHBOT_TOKEN": "tok-abc",
    "SNITCHBOT_CHAT_ID": "123456",
}


def test_config_reads_all_env_vars(monkeypatch):
    """
    Given all required + optional env vars are set,
    When SnitchbotConfig.from_env() is called,
    Then all fields are populated correctly.
    """
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SNITCHBOT_SIDECAR_LOG", "/var/log/snitchbot.log")
    monkeypatch.setenv("SNITCHBOT_TZ", "Europe/Berlin")
    monkeypatch.setenv("SNITCHBOT_DEBUG", "true")

    cfg = SnitchbotConfig.from_env()

    assert cfg.socket_path == "/tmp/test.sock"
    assert cfg.sidecar_service == "test-service"
    assert cfg.token == "tok-abc"
    assert cfg.chat_id == "123456"
    assert cfg.log_path == "/var/log/snitchbot.log"
    assert cfg.tz == "Europe/Berlin"
    assert cfg.debug is True


def test_missing_token_raises(monkeypatch):
    """
    Given SNITCHBOT_TOKEN is absent,
    When SnitchbotConfig is constructed,
    Then ValidationError is raised.
    """
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SNITCHBOT_TOKEN", raising=False)

    with pytest.raises(ValidationError):
        SnitchbotConfig(_env_file="/dev/null")


def test_missing_chat_id_raises(monkeypatch):
    """
    Given SNITCHBOT_CHAT_ID is absent,
    When SnitchbotConfig is constructed,
    Then ValidationError is raised.
    """
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SNITCHBOT_CHAT_ID", raising=False)

    with pytest.raises(ValidationError):
        SnitchbotConfig(_env_file="/dev/null")


@pytest.mark.parametrize("value", ["1", "true", "yes", "TRUE", "YES"])
def test_debug_flag_parsed_true(monkeypatch, value):
    """
    Given SNITCHBOT_DEBUG is set to a truthy string,
    When SnitchbotConfig.from_env() is called,
    Then debug is True.
    """
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SNITCHBOT_DEBUG", value)

    cfg = SnitchbotConfig.from_env()

    assert cfg.debug is True


def test_debug_flag_default_false(monkeypatch):
    """
    Given SNITCHBOT_DEBUG is absent,
    When SnitchbotConfig.from_env() is called,
    Then debug is False.
    """
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SNITCHBOT_DEBUG", raising=False)

    cfg = SnitchbotConfig.from_env()

    assert cfg.debug is False


def test_optional_fields_none_when_absent(monkeypatch):
    """
    Given only required env vars are set,
    When SnitchbotConfig.from_env() is called,
    Then sidecar_log and tz are None.
    """
    for k, v in REQUIRED.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("SNITCHBOT_SIDECAR_LOG", raising=False)
    monkeypatch.delenv("SNITCHBOT_TZ", raising=False)

    cfg = SnitchbotConfig.from_env()

    assert cfg.log_path is None
    assert cfg.tz is None
