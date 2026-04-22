import pytest
from snitchbot.sidecar.telegram_io.domain.topic_mapping_vo import TopicMappingVO
from snitchbot.sidecar.telegram_io.domain.services.topic_registry_service import (
    TopicRegistry,
)


class TestTopicRegistry:
    def test_lookup_unknown_returns_none(self):
        r = TopicRegistry()
        assert r.lookup("svc-x") is None
        assert r.reverse_lookup(123) is None

    def test_register_and_lookup_roundtrip(self):
        r = TopicRegistry()
        m = TopicMappingVO(service="svc-a", message_thread_id=42, created_at=1.0)
        r.register(m)
        assert r.lookup("svc-a") == m
        assert r.reverse_lookup(42) == "svc-a"

    def test_register_same_service_twice_replaces_mapping(self):
        r = TopicRegistry()
        r.register(TopicMappingVO(service="x", message_thread_id=1, created_at=0.0))
        r.register(TopicMappingVO(service="x", message_thread_id=2, created_at=1.0))
        assert r.lookup("x").message_thread_id == 2
        assert r.reverse_lookup(1) is None
        assert r.reverse_lookup(2) == "x"

    def test_forget_removes_both_directions(self):
        r = TopicRegistry()
        r.register(TopicMappingVO(service="x", message_thread_id=1, created_at=0.0))
        r.forget("x")
        assert r.lookup("x") is None
        assert r.reverse_lookup(1) is None

    def test_forget_unknown_is_noop(self):
        TopicRegistry().forget("nope")  # must not raise

    def test_snapshot_returns_immutable_view(self):
        r = TopicRegistry()
        r.register(TopicMappingVO(service="x", message_thread_id=1, created_at=0.0))
        snap = r.snapshot()
        assert snap == (TopicMappingVO(service="x", message_thread_id=1, created_at=0.0),)
        with pytest.raises(TypeError):
            snap[0] = None  # type: ignore[index]

    def test_bulk_load_replaces_state(self):
        r = TopicRegistry()
        r.register(TopicMappingVO(service="old", message_thread_id=99, created_at=0.0))
        r.bulk_load([
            TopicMappingVO(service="a", message_thread_id=1, created_at=0.0),
            TopicMappingVO(service="b", message_thread_id=2, created_at=0.0),
        ])
        assert r.lookup("old") is None
        assert r.lookup("a").message_thread_id == 1
        assert r.lookup("b").message_thread_id == 2
        assert r.reverse_lookup(99) is None
