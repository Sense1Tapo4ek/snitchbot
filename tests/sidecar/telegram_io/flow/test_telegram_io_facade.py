"""Flow tests for TelegramIOFacade forum-mode surface (Invariants F1, F3, F5, F6)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from snitchbot.sidecar.telegram_io.domain.forum_mode_vo import ForumModeVO
from snitchbot.sidecar.telegram_io.domain.services.topic_color_service import (
    TOPIC_COLOR_PALETTE,
)
from snitchbot.sidecar.telegram_io.domain.services.topic_registry_service import (
    TopicRegistry,
)
from snitchbot.sidecar.telegram_io.domain.topic_mapping_vo import TopicMappingVO
from snitchbot.sidecar.telegram_io.ports.driving.telegram_io_facade import (
    TelegramIOFacade,
)


@pytest.fixture
def mock_gateway():
    g = MagicMock()
    g.close = AsyncMock()
    return g


@pytest.fixture
def mock_set_commands_uc():
    return AsyncMock()


@pytest.fixture
def mock_resolve_uc():
    uc = MagicMock()
    uc.__call__ = AsyncMock(return_value=42)
    # Make the instance itself awaitable like the real UC (it defines __call__).
    # MagicMock's side_effect on direct call works once we treat uc as AsyncMock.
    return uc


@pytest.fixture
def registry():
    return TopicRegistry()


@pytest.fixture
def forum_mode_capable():
    return ForumModeVO(is_forum=True, can_manage_topics=True)


@pytest.fixture
def forum_mode_simple():
    return ForumModeVO(is_forum=False, can_manage_topics=None)


class TestForumModeProperty:
    def test_property_returns_injected_vo(
        self, mock_gateway, mock_set_commands_uc, forum_mode_capable, registry,
    ):
        """
        Given a facade built with a specific ForumModeVO,
        When reading .forum_mode,
        Then the injected instance is returned unchanged.
        """
        # Arrange
        facade = TelegramIOFacade(
            _gateway=mock_gateway,
            _set_commands_uc=mock_set_commands_uc,
            _forum_mode=forum_mode_capable,
            _registry=registry,
            _resolve_topic_uc=AsyncMock(),
        )

        # Act / Assert
        assert facade.forum_mode is forum_mode_capable
        assert facade.forum_mode.fully_capable is True


@pytest.mark.asyncio
class TestResolveTopicSimpleMode:
    async def test_simple_mode_returns_none_without_calling_use_case(
        self, mock_gateway, mock_set_commands_uc, forum_mode_simple, registry,
    ):
        """
        Given a facade in simple (non-forum) mode,
        When resolve_topic is called,
        Then None is returned and the resolve use case is never invoked.
        """
        # Arrange
        resolve_uc = AsyncMock()
        facade = TelegramIOFacade(
            _gateway=mock_gateway,
            _set_commands_uc=mock_set_commands_uc,
            _forum_mode=forum_mode_simple,
            _registry=registry,
            _resolve_topic_uc=resolve_uc,
        )

        # Act
        result = await facade.resolve_topic(service="orders-api")

        # Assert
        assert result is None
        resolve_uc.assert_not_called()


@pytest.mark.asyncio
class TestResolveTopicForumMode:
    async def test_auto_derived_color_passed_to_use_case(
        self, mock_gateway, mock_set_commands_uc, forum_mode_capable, registry,
    ):
        """
        Given fully-capable forum mode and no override,
        When resolve_topic is called,
        Then the use case is invoked with a color from the Telegram palette.
        """
        # Arrange
        resolve_uc = AsyncMock(return_value=777)
        facade = TelegramIOFacade(
            _gateway=mock_gateway,
            _set_commands_uc=mock_set_commands_uc,
            _forum_mode=forum_mode_capable,
            _registry=registry,
            _resolve_topic_uc=resolve_uc,
        )

        # Act
        result = await facade.resolve_topic(service="orders-api")

        # Assert
        assert result == 777
        resolve_uc.assert_awaited_once()
        kwargs = resolve_uc.await_args.kwargs
        assert kwargs["service"] == "orders-api"
        assert kwargs["icon_color"] in TOPIC_COLOR_PALETTE

    async def test_override_color_is_respected(
        self, mock_gateway, mock_set_commands_uc, forum_mode_capable, registry,
    ):
        """
        Given a _color_overrides mapping for the service,
        When resolve_topic is called,
        Then the use case receives the exact overridden color.
        """
        # Arrange
        resolve_uc = AsyncMock(return_value=77)
        chosen = TOPIC_COLOR_PALETTE[3]
        facade = TelegramIOFacade(
            _gateway=mock_gateway,
            _set_commands_uc=mock_set_commands_uc,
            _forum_mode=forum_mode_capable,
            _registry=registry,
            _resolve_topic_uc=resolve_uc,
            _color_overrides={"orders-api": chosen},
        )

        # Act
        await facade.resolve_topic(service="orders-api")

        # Assert
        resolve_uc.assert_awaited_once_with(service="orders-api", icon_color=chosen)


class TestReverseLookup:
    def test_reverse_lookup_returns_registered_service(
        self, mock_gateway, mock_set_commands_uc, forum_mode_capable, registry,
    ):
        """
        Given a service mapped to thread_id 99 in the registry,
        When reverse_lookup(99) is called,
        Then the service name is returned.
        """
        # Arrange
        registry.register(
            TopicMappingVO(service="billing", message_thread_id=99, created_at=0.0)
        )
        facade = TelegramIOFacade(
            _gateway=mock_gateway,
            _set_commands_uc=mock_set_commands_uc,
            _forum_mode=forum_mode_capable,
            _registry=registry,
            _resolve_topic_uc=AsyncMock(),
        )

        # Act / Assert
        assert facade.reverse_lookup(99) == "billing"
        assert facade.reverse_lookup(12345) is None


class TestInvalidateTopic:
    def test_invalidate_delegates_to_use_case(
        self, mock_gateway, mock_set_commands_uc, forum_mode_capable, registry,
    ):
        """
        Given a facade with a resolve use case,
        When invalidate_topic(service) is called,
        Then the use case's invalidate method is called exactly once.
        """
        # Arrange
        resolve_uc = MagicMock()
        resolve_uc.invalidate = MagicMock()
        facade = TelegramIOFacade(
            _gateway=mock_gateway,
            _set_commands_uc=mock_set_commands_uc,
            _forum_mode=forum_mode_capable,
            _registry=registry,
            _resolve_topic_uc=resolve_uc,
        )

        # Act
        facade.invalidate_topic("billing")

        # Assert
        resolve_uc.invalidate.assert_called_once_with("billing")
