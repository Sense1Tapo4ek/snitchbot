import pytest
from snitchbot.sidecar.telegram_io.domain.forum_mode_vo import ForumModeVO


class TestForumModeVOConstruction:
    def test_simple_mode_has_no_admin_rights_check(self):
        """
        Given a simple-mode VO,
        When inspecting it,
        Then is_forum is False and can_manage_topics is None.
        """
        m = ForumModeVO(is_forum=False, can_manage_topics=None)
        assert m.is_forum is False
        assert m.can_manage_topics is None
        assert m.fully_capable is False

    def test_forum_mode_with_rights_is_fully_capable(self):
        m = ForumModeVO(is_forum=True, can_manage_topics=True)
        assert m.fully_capable is True

    def test_forum_mode_without_rights_is_degraded(self):
        m = ForumModeVO(is_forum=True, can_manage_topics=False)
        assert m.is_forum is True
        assert m.fully_capable is False
