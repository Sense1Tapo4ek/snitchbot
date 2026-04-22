"""Flow tests for ResolveTopicUseCase (Invariants F3, F4, F6)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from snitchbot.sidecar.telegram_io.app.use_cases.resolve_topic_uc import (
    ResolveTopicUseCase,
)
from snitchbot.sidecar.telegram_io.domain.services.topic_registry_service import (
    TopicRegistry,
)
from snitchbot.sidecar.telegram_io.domain.topic_mapping_vo import TopicMappingVO
from snitchbot.sidecar.telegram_io.ports.driven.tg_errors import TgPermissionError


@pytest.fixture
def fake_store():
    s = MagicMock()
    s.load.return_value = []
    s.save = MagicMock()
    return s


@pytest.fixture
def fake_gateway():
    g = MagicMock()
    g.create_forum_topic = AsyncMock()
    return g


@pytest.fixture
def registry():
    return TopicRegistry()


@pytest.fixture
def now():
    counter = {"v": 100.0}

    def _now() -> float:
        counter["v"] += 1
        return counter["v"]

    return _now


@pytest.mark.asyncio
class TestResolveTopicCacheHit:
    async def test_returns_existing_thread_id_without_api_call(
        self, fake_store, fake_gateway, registry, now,
    ):
        """
        Given a mapping already in the registry,
        When resolving that service,
        Then cached thread_id is returned without touching gateway or store.
        """
        # Arrange
        registry.register(
            TopicMappingVO(service="x", message_thread_id=42, created_at=0.0)
        )
        uc = ResolveTopicUseCase(
            _registry=registry, _store=fake_store, _gateway=fake_gateway,
            _chat_id="-1001", _now=now,
        )

        # Act
        thread_id = await uc(service="x", icon_color=9367192)

        # Assert
        assert thread_id == 42
        fake_gateway.create_forum_topic.assert_not_called()
        fake_store.save.assert_not_called()


@pytest.mark.asyncio
class TestResolveTopicCacheMiss:
    async def test_creates_topic_persists_and_registers(
        self, fake_store, fake_gateway, registry, now,
    ):
        """
        Given empty registry,
        When resolving a new service,
        Then create_forum_topic is called, mapping is persisted and registered.
        """
        # Arrange
        fake_gateway.create_forum_topic = AsyncMock(return_value=77)
        uc = ResolveTopicUseCase(
            _registry=registry, _store=fake_store, _gateway=fake_gateway,
            _chat_id="-1001", _now=now,
        )

        # Act
        thread_id = await uc(service="orders-api", icon_color=9367192)

        # Assert
        assert thread_id == 77
        fake_gateway.create_forum_topic.assert_called_once_with(
            chat_id="-1001", name="orders-api", icon_color=9367192,
        )
        saved = fake_store.save.call_args[0][0]
        assert len(saved) == 1
        assert saved[0].service == "orders-api"
        assert saved[0].message_thread_id == 77
        assert registry.lookup("orders-api").message_thread_id == 77


@pytest.mark.asyncio
class TestResolveTopicConcurrency:
    async def test_two_concurrent_calls_for_same_service_create_one_topic(
        self, fake_store, fake_gateway, registry, now,
    ):
        """
        Given two concurrent resolves for the same service,
        When the first is still in flight,
        Then create_forum_topic is called exactly once (F4).
        """
        # Arrange
        async def slow_create(**_):
            await asyncio.sleep(0.05)
            return 42

        fake_gateway.create_forum_topic = AsyncMock(side_effect=slow_create)
        uc = ResolveTopicUseCase(
            _registry=registry, _store=fake_store, _gateway=fake_gateway,
            _chat_id="-1001", _now=now,
        )

        # Act
        results = await asyncio.gather(
            uc(service="x", icon_color=9367192),
            uc(service="x", icon_color=9367192),
        )

        # Assert
        assert results == [42, 42]
        assert fake_gateway.create_forum_topic.call_count == 1  # F4

    async def test_concurrent_calls_for_different_services_create_two_topics(
        self, fake_store, fake_gateway, registry, now,
    ):
        """
        Given two concurrent resolves for DIFFERENT services,
        When both run in parallel,
        Then both create_forum_topic calls are made (lock is per-service).
        """
        # Arrange
        threads = {"a": 1, "b": 2}

        async def create(*, chat_id, name, icon_color):
            return threads[name]

        fake_gateway.create_forum_topic = AsyncMock(side_effect=create)
        uc = ResolveTopicUseCase(
            _registry=registry, _store=fake_store, _gateway=fake_gateway,
            _chat_id="-1001", _now=now,
        )

        # Act
        a, b = await asyncio.gather(
            uc(service="a", icon_color=9367192),
            uc(service="b", icon_color=9367192),
        )

        # Assert
        assert {a, b} == {1, 2}


@pytest.mark.asyncio
class TestResolveTopicPermissionFallback:
    async def test_permission_error_returns_none(
        self, fake_store, fake_gateway, registry, now,
    ):
        """F6: missing can_manage_topics => resolver returns None (caller routes to General)."""
        # Arrange
        fake_gateway.create_forum_topic = AsyncMock(side_effect=TgPermissionError())
        uc = ResolveTopicUseCase(
            _registry=registry, _store=fake_store, _gateway=fake_gateway,
            _chat_id="-1001", _now=now,
        )

        # Act
        thread_id = await uc(service="x", icon_color=9367192)

        # Assert
        assert thread_id is None
        assert registry.lookup("x") is None


@pytest.mark.asyncio
class TestResolveTopicForget:
    async def test_invalidate_removes_mapping(
        self, fake_store, fake_gateway, registry, now,
    ):
        """
        Given an existing mapping,
        When invalidate(service) is called,
        Then the registry no longer contains it and the store is saved.
        """
        # Arrange
        registry.register(
            TopicMappingVO(service="x", message_thread_id=99, created_at=0.0)
        )
        uc = ResolveTopicUseCase(
            _registry=registry, _store=fake_store, _gateway=fake_gateway,
            _chat_id="-1001", _now=now,
        )

        # Act
        uc.invalidate("x")

        # Assert
        assert registry.lookup("x") is None
        fake_store.save.assert_called_once()
