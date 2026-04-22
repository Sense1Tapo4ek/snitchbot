"""F-T16: snitchbot.init() accepts forum + topic_color kwargs and validates them."""
import os
from unittest.mock import patch

import pytest

import snitchbot
from snitchbot.sidecar.telegram_io.domain.services.topic_color_service import (
    TOPIC_COLOR_PALETTE,
)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Each test: clean slate — kill switch on so init returns early after validation."""
    # Reset module globals so repeated init() calls don't short-circuit on idempotency.
    from snitchbot.client.ports.driving import public_api as p
    monkeypatch.setattr(p, "_initialized", False)
    monkeypatch.setattr(p, "_initialized_pid", None)
    monkeypatch.setattr(p, "_stored_config", None)
    # Strip any forum env from earlier tests
    for k in ("SNITCHBOT_FORUM", "SNITCHBOT_TOPIC_COLOR"):
        os.environ.pop(k, None)
    yield
    for k in ("SNITCHBOT_FORUM", "SNITCHBOT_TOPIC_COLOR"):
        os.environ.pop(k, None)


def _call(forum="auto", topic_color=None):
    """init() with kill-switch via env so it returns BEFORE _init_impl."""
    # We do validation BEFORE the disabled-check? No — disabled returns early
    # before validation. Use disabled=True so we don't spawn a sidecar but also
    # bypass validation. To exercise validation, set disabled=False AND mock
    # _init_impl out to no-op.
    with patch(
        "snitchbot.client.ports.driving.public_api._init_impl"
    ) as m:
        m.return_value = None
        snitchbot.init(
            "svc-test",
            token="dummy_token",
            chat_id="-1001",
            forum=forum,
            topic_color=topic_color,
        )


class TestInitForumKwargs:
    def test_forum_true_sets_env(self):
        _call(forum=True)
        assert os.environ.get("SNITCHBOT_FORUM") == "true"

    def test_forum_false_sets_env(self):
        _call(forum=False)
        assert os.environ.get("SNITCHBOT_FORUM") == "false"

    def test_forum_auto_does_not_set_env(self):
        _call(forum="auto")
        assert "SNITCHBOT_FORUM" not in os.environ

    def test_topic_color_in_palette_sets_env(self):
        chosen = TOPIC_COLOR_PALETTE[2]
        _call(topic_color=chosen)
        assert os.environ.get("SNITCHBOT_TOPIC_COLOR") == str(chosen)

    def test_topic_color_none_does_not_set_env(self):
        _call(topic_color=None)
        assert "SNITCHBOT_TOPIC_COLOR" not in os.environ


class TestInitForumValidation:
    def test_invalid_forum_value_raises(self):
        with pytest.raises(ValueError, match="forum"):
            snitchbot.init(
                "svc", token="dummy_token", chat_id="-1001", forum="maybe",  # type: ignore[arg-type]
            )

    def test_topic_color_outside_palette_raises(self):
        with pytest.raises(ValueError, match="palette"):
            snitchbot.init(
                "svc", token="dummy_token", chat_id="-1001", topic_color=999999,
            )
