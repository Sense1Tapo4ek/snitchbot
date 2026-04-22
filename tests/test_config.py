"""Tests for SnitchbotConfig and init_from_env."""
from unittest.mock import patch

import pytest
from pydantic import ValidationError

import snitchbot
from snitchbot.config import SnitchbotConfig


class TestSnitchbotConfig:
    def test_config_reads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Given SNITCHBOT_TOKEN and SNITCHBOT_CHAT_ID set in env,
        When constructing SnitchbotConfig,
        Then token and chat_id are populated correctly.
        """
        monkeypatch.setenv("SNITCHBOT_TOKEN", "tok-abc")
        monkeypatch.setenv("SNITCHBOT_CHAT_ID", "12345")

        cfg = SnitchbotConfig()

        assert cfg.token == "tok-abc"
        assert cfg.chat_id == "12345"

    def test_config_missing_token_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Given no SNITCHBOT_TOKEN in env and no .env file,
        When constructing SnitchbotConfig,
        Then ValidationError is raised.
        """
        monkeypatch.delenv("SNITCHBOT_TOKEN", raising=False)
        monkeypatch.delenv("SNITCHBOT_CHAT_ID", raising=False)

        # Override env_file so the real .env on disk is not loaded
        with pytest.raises(ValidationError):
            SnitchbotConfig(_env_file="/dev/null")  # type: ignore[call-arg]

    def test_config_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Given only required fields provided,
        When constructing SnitchbotConfig,
        Then service defaults to 'default' and disabled defaults to False.
        """
        monkeypatch.setenv("SNITCHBOT_TOKEN", "tok-xyz")
        monkeypatch.setenv("SNITCHBOT_CHAT_ID", "99")

        cfg = SnitchbotConfig()

        assert cfg.service == "default"
        assert cfg.disabled is False


class TestInitReadsEnv:
    def test_init_reads_token_from_env_when_not_passed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Given SNITCHBOT_TOKEN and SNITCHBOT_CHAT_ID in env,
        When init() is called without token/chat_id args,
        Then values are read from env via SnitchbotConfig.
        """
        monkeypatch.setenv("SNITCHBOT_TOKEN", "tok-env")
        monkeypatch.setenv("SNITCHBOT_CHAT_ID", "777")

        with patch("snitchbot.client.ports.driving.public_api._init_impl"):
            from snitchbot.client.ports.driving import public_api as pa
            old = (pa._initialized, pa._initialized_pid)
            pa._initialized = False
            pa._initialized_pid = None
            try:
                pa.init("my-service")  # no token/chat_id args
            finally:
                pa._initialized, pa._initialized_pid = old
