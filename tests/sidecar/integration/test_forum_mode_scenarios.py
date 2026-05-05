"""Forum-mode integration scenarios (F1, F2, F3, F4, F5, F6).

These are in-process integration tests that wire the REAL composition used
by the sidecar (F-T17) against a fake Telegram gateway. They exercise the
full integration between:

    facade -> resolve_topic_uc -> registry -> json store
    dispatch retry loop -> invalidate_topic -> re-resolve -> send_message

Scope notes
-----------
The dispatch-driven scenarios (3, 4) instantiate the REAL
``DispatchLoopWorkflow`` together with real ``CentralQueue`` / ``RateBucket``
/ ``DedupCache`` because the F5 retry-and-invalidate logic lives inside
the workflow itself; exercising it there is what gives these tests their
integration value.

A subprocess + mock-HTTPS-server harness (as originally envisioned in the
plan) would buy us little more coverage for forum-mode specifically, so we
keep the tests fully in-process and drive a ``AsyncMock`` for the gateway.
"""
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from snitchbot.shared.ports.i_telegram_gateway import ITelegramGateway
from snitchbot.sidecar.pipeline.app.workflows.dispatch_loop_workflow import (
    DispatchLoopWorkflow,
)
from snitchbot.sidecar.pipeline.domain.central_queue_agg import (
    CentralQueue,
    QueueItem,
    QueuePriority,
)
from snitchbot.sidecar.pipeline.domain.dedup_cache_agg import DedupCache
from snitchbot.sidecar.pipeline.domain.rate_bucket_vo import RateBucket
from snitchbot.sidecar.telegram_io.app.use_cases.resolve_topic_uc import (
    ResolveTopicUseCase,
)
from snitchbot.sidecar.telegram_io.domain.forum_mode_vo import ForumModeVO
from snitchbot.sidecar.telegram_io.domain.services.topic_registry_service import (
    TopicRegistry,
)
from snitchbot.sidecar.telegram_io.ports.driven.persistence.topic_store_json import (
    JsonFileTopicStore,
)
from snitchbot.sidecar.telegram_io.ports.driven.tg_errors import (
    TgThreadNotFoundError,
)
from snitchbot.sidecar.telegram_io.ports.driving.telegram_io_facade import (
    TelegramIOFacade,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_gateway(*, send_return: int = 1000) -> AsyncMock:
    """AsyncMock matching the ITelegramGateway surface.

    ``create_forum_topic`` is not in the shared Protocol (it's on the concrete
    gateway), so we attach it manually.
    """
    gw = AsyncMock(spec=ITelegramGateway)
    gw.send_message.return_value = send_return
    gw.create_forum_topic = AsyncMock()
    return gw


def _monotonic_clock() -> "_Clock":
    return _Clock()


class _Clock:
    """Deterministic monotonically-increasing clock for tests."""

    def __init__(self) -> None:
        self._t = 1_700_000_000.0

    def __call__(self) -> float:
        self._t += 1.0
        return self._t


def _build_facade(
    *,
    forum_mode: ForumModeVO,
    registry: TopicRegistry,
    store: JsonFileTopicStore,
    gateway: AsyncMock,
    chat_id: str = "-1001",
) -> TelegramIOFacade:
    """Compose a real TelegramIOFacade with real forum-mode wiring."""
    resolve_uc = ResolveTopicUseCase(
        _registry=registry,
        _store=store,
        _gateway=cast("object", gateway),  # gateway only needs create_forum_topic
        _chat_id=chat_id,
        _now=_monotonic_clock(),
    )
    return TelegramIOFacade(
        _gateway=cast(ITelegramGateway, gateway),
        _set_commands_uc=cast("object", AsyncMock()),  # not exercised here
        _forum_mode=forum_mode,
        _registry=registry,
        _resolve_topic_uc=resolve_uc,
    )


def _build_workflow(
    *,
    gateway: AsyncMock,
    facade: TelegramIOFacade,
    chat_id: str = "-1001",
) -> tuple[DispatchLoopWorkflow, CentralQueue]:
    """Real queue + real rate bucket + real dedup + real workflow."""
    queue = CentralQueue()
    rate_bucket = RateBucket(capacity=30, refill_rate=0.5)
    dedup = DedupCache()
    return (
        DispatchLoopWorkflow(
            _queue=queue,
            _rate_bucket=rate_bucket,
            _dedup_cache=dedup,
            _render_fn=lambda event, dedup_entry=None: "<b>alert</b>",
            _gateway=cast(ITelegramGateway, gateway),
            _chat_id=chat_id,
            _telegram_io=facade,
        ),
        queue,
    )


def _enqueue_alert(queue: CentralQueue, *, service: str) -> None:
    queue.enqueue(
        QueueItem(
            priority=QueuePriority.NEW_ALERT,
            payload={
                "kind": "error",
                "action": "new_alert",
                "fingerprint": f"fp-{service}",
                "service": service,
                "payload": {"msg": "boom"},
            },
        )
    )


# ---------------------------------------------------------------------------
# Scenario 1 — two services create two topics (F2, F3, F4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTwoServicesCreateTwoTopics:
    async def test_each_service_gets_its_own_thread_and_mappings_persist(
        self, tmp_path: Path,
    ) -> None:
        """
        Given a fresh registry and JSON store in forum mode,
        When two services resolve their topics in sequence,
        Then each gets a distinct thread_id and both mappings are persisted.
        """
        # Arrange
        gateway = _fake_gateway()
        gateway.create_forum_topic.side_effect = [10, 20]

        registry = TopicRegistry()
        store_path = tmp_path / "topics.json"
        store = JsonFileTopicStore(store_path)
        facade = _build_facade(
            forum_mode=ForumModeVO(is_forum=True, can_manage_topics=True),
            registry=registry,
            store=store,
            gateway=gateway,
        )

        # Act
        orders_thread = await facade.resolve_topic(service="orders-api")
        billing_thread = await facade.resolve_topic(service="billing-api")

        # Assert — returned ids match the gateway's create results
        assert orders_thread == 10
        assert billing_thread == 20

        # Gateway received exactly two createForumTopic calls
        assert gateway.create_forum_topic.await_count == 2
        services_created = [
            c.kwargs["name"] for c in gateway.create_forum_topic.await_args_list
        ]
        assert services_created == ["orders-api", "billing-api"]

        # Mappings persisted to disk and round-trip into a fresh registry
        assert store_path.exists()
        fresh_registry = TopicRegistry()
        fresh_store = JsonFileTopicStore(store_path)
        fresh_registry.bulk_load(fresh_store.load())
        orders_mapping = fresh_registry.lookup("orders-api")
        billing_mapping = fresh_registry.lookup("billing-api")
        assert orders_mapping is not None
        assert billing_mapping is not None
        assert orders_mapping.message_thread_id == 10
        assert billing_mapping.message_thread_id == 20


# ---------------------------------------------------------------------------
# Scenario 2 — topic persisted across sidecar restart (F2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTopicPersistedAcrossRestart:
    async def test_second_sidecar_reuses_mapping_without_recreating(
        self, tmp_path: Path,
    ) -> None:
        """
        Given a service resolved its topic with the first sidecar instance,
        When a second sidecar instance (new registry + facade, same JSON store)
            resolves the same service,
        Then the cached thread_id is returned and create_forum_topic is NOT
            called a second time.
        """
        # Arrange — first sidecar instance creates the topic
        gateway = _fake_gateway()
        gateway.create_forum_topic.side_effect = [10]

        registry_a = TopicRegistry()
        store_path = tmp_path / "topics.json"
        store_a = JsonFileTopicStore(store_path)
        facade_a = _build_facade(
            forum_mode=ForumModeVO(is_forum=True, can_manage_topics=True),
            registry=registry_a,
            store=store_a,
            gateway=gateway,
        )
        first = await facade_a.resolve_topic(service="orders-api")
        assert first == 10
        assert gateway.create_forum_topic.await_count == 1

        # Act — second sidecar instance loads from disk and resolves again
        registry_b = TopicRegistry()
        store_b = JsonFileTopicStore(store_path)
        registry_b.bulk_load(store_b.load())  # mirrors real startup
        facade_b = _build_facade(
            forum_mode=ForumModeVO(is_forum=True, can_manage_topics=True),
            registry=registry_b,
            store=store_b,
            gateway=gateway,
        )
        second = await facade_b.resolve_topic(service="orders-api")

        # Assert — same id returned from disk, no new creation call
        assert second == 10
        assert gateway.create_forum_topic.await_count == 1


# ---------------------------------------------------------------------------
# Scenario 3 — thread-not-found recreates topic (F5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestThreadNotFoundRecreatesTopic:
    async def test_stale_thread_triggers_invalidate_and_retry_with_new_id(
        self, tmp_path: Path,
    ) -> None:
        """
        Given a service has a cached thread_id 99 that no longer exists on TG,
        When dispatch sends an event and TG returns `thread not found`,
        Then the workflow invalidates the mapping, re-resolves (creating 200),
            retries send_message once, and the second call succeeds with id 5678.
        """
        # Arrange — real workflow, real registry, real store, fake gateway
        gateway = _fake_gateway()
        gateway.create_forum_topic.side_effect = [99, 200]
        gateway.send_message.side_effect = [
            TgThreadNotFoundError(),
            5678,
        ]

        registry = TopicRegistry()
        store = JsonFileTopicStore(tmp_path / "topics.json")
        facade = _build_facade(
            forum_mode=ForumModeVO(is_forum=True, can_manage_topics=True),
            registry=registry,
            store=store,
            gateway=gateway,
        )
        workflow, queue = _build_workflow(gateway=gateway, facade=facade)
        _enqueue_alert(queue, service="x")

        # Act
        await workflow.tick()

        # Assert — two topic creates (initial + post-invalidate)
        assert gateway.create_forum_topic.await_count == 2

        # Two send_message attempts, with thread_ids 99 then 200
        assert gateway.send_message.await_count == 2
        sent_thread_ids = [
            c.kwargs["message_thread_id"]
            for c in gateway.send_message.await_args_list
        ]
        assert sent_thread_ids == [99, 200]

        # Registry now points to the fresh id; 99 is forgotten both ways
        mapping = registry.lookup("x")
        assert mapping is not None
        assert mapping.message_thread_id == 200
        assert registry.reverse_lookup(99) is None
        assert registry.reverse_lookup(200) == "x"


# ---------------------------------------------------------------------------
# Scenario 4 — missing can_manage_topics falls back to General (F6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDegradedForumFallsBackToGeneral:
    async def test_resolve_returns_none_and_send_omits_thread_id(
        self, tmp_path: Path,
    ) -> None:
        """
        Given forum chat but bot lacks can_manage_topics,
        When a service resolves its topic and dispatch sends an event,
        Then resolve returns None, create_forum_topic is NEVER called,
            and send_message is invoked with message_thread_id=None
            (which routes to General).
        """
        # Arrange
        gateway = _fake_gateway(send_return=4242)
        registry = TopicRegistry()
        store = JsonFileTopicStore(tmp_path / "topics.json")
        facade = _build_facade(
            forum_mode=ForumModeVO(is_forum=True, can_manage_topics=False),
            registry=registry,
            store=store,
            gateway=gateway,
        )

        # Act — direct facade probe
        thread_id = await facade.resolve_topic(service="x")

        # Assert — no topic creation, degraded mode short-circuits
        assert thread_id is None
        gateway.create_forum_topic.assert_not_called()

        # Act — drive a send through the dispatch workflow
        workflow, queue = _build_workflow(gateway=gateway, facade=facade)
        _enqueue_alert(queue, service="x")
        await workflow.tick()

        # Assert — send_message called with message_thread_id=None
        gateway.send_message.assert_awaited_once()
        call_kwargs = gateway.send_message.await_args.kwargs
        assert call_kwargs["message_thread_id"] is None
        gateway.create_forum_topic.assert_not_called()


# ---------------------------------------------------------------------------
# Scenario 5 — simple (private) chat skips forum entirely (F1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSimpleModeWhenChatIsPrivate:
    async def test_resolve_returns_none_and_no_topic_ever_created(
        self, tmp_path: Path,
    ) -> None:
        """
        Given a non-forum chat (simple mode),
        When resolve_topic is called and dispatch sends an event,
        Then resolve returns None unconditionally, create_forum_topic is never
            invoked, and send_message is called without message_thread_id.
        """
        # Arrange
        gateway = _fake_gateway(send_return=1)
        registry = TopicRegistry()
        store = JsonFileTopicStore(tmp_path / "topics.json")
        facade = _build_facade(
            forum_mode=ForumModeVO(is_forum=False, can_manage_topics=None),
            registry=registry,
            store=store,
            gateway=gateway,
        )

        # Act — direct facade probe
        thread_id = await facade.resolve_topic(service="any")

        # Assert
        assert thread_id is None
        gateway.create_forum_topic.assert_not_called()

        # Act — drive a send through the dispatch workflow
        workflow, queue = _build_workflow(gateway=gateway, facade=facade)
        _enqueue_alert(queue, service="any")
        await workflow.tick()

        # Assert — send_message called without a thread id
        gateway.send_message.assert_awaited_once()
        call_kwargs = gateway.send_message.await_args.kwargs
        assert call_kwargs["message_thread_id"] is None
        gateway.create_forum_topic.assert_not_called()
