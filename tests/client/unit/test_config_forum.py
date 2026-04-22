"""F-T15: SnitchbotConfig forum + topic_color fields with validation."""
import pytest

from snitchbot.config import SnitchbotConfig
from snitchbot.sidecar.telegram_io.domain.services.topic_color_service import (
    TOPIC_COLOR_PALETTE,
)


class TestSnitchbotConfigForumDefaults:
    def test_default_forum_is_auto(self):
        c = SnitchbotConfig(token="t", chat_id="c")
        assert c.forum == "auto"

    def test_default_topic_color_is_none(self):
        c = SnitchbotConfig(token="t", chat_id="c")
        assert c.topic_color is None


class TestSnitchbotConfigForumExplicit:
    def test_forum_true(self):
        c = SnitchbotConfig(token="t", chat_id="c", forum=True)
        assert c.forum is True

    def test_forum_false(self):
        c = SnitchbotConfig(token="t", chat_id="c", forum=False)
        assert c.forum is False

    def test_forum_auto_string(self):
        c = SnitchbotConfig(token="t", chat_id="c", forum="auto")
        assert c.forum == "auto"

    def test_invalid_forum_value_rejected(self):
        with pytest.raises(ValueError, match="forum"):
            SnitchbotConfig(token="t", chat_id="c", forum="maybe")  # type: ignore[arg-type]


class TestSnitchbotConfigTopicColor:
    def test_topic_color_in_palette_accepted(self):
        c = SnitchbotConfig(token="t", chat_id="c", topic_color=TOPIC_COLOR_PALETTE[0])
        assert c.topic_color == TOPIC_COLOR_PALETTE[0]

    def test_topic_color_outside_palette_rejected(self):
        with pytest.raises(ValueError, match="palette"):
            SnitchbotConfig(token="t", chat_id="c", topic_color=999999)
