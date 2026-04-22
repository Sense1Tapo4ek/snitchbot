import pytest
from snitchbot.sidecar.telegram_io.domain.topic_mapping_vo import TopicMappingVO


class TestTopicMappingVO:
    def test_constructs_with_required_fields(self):
        """Given service+thread_id+created_at, When constructed, Then attrs match."""
        m = TopicMappingVO(service="orders-api", message_thread_id=42, created_at=123.0)
        assert m.service == "orders-api"
        assert m.message_thread_id == 42
        assert m.created_at == 123.0

    def test_is_frozen(self):
        m = TopicMappingVO(service="x", message_thread_id=1, created_at=0.0)
        with pytest.raises(Exception):
            m.service = "y"  # type: ignore[misc]

    def test_rejects_zero_or_negative_thread_id(self):
        with pytest.raises(ValueError, match="message_thread_id"):
            TopicMappingVO(service="x", message_thread_id=0, created_at=0.0)
        with pytest.raises(ValueError, match="message_thread_id"):
            TopicMappingVO(service="x", message_thread_id=-1, created_at=0.0)

    def test_rejects_empty_service(self):
        with pytest.raises(ValueError, match="service"):
            TopicMappingVO(service="", message_thread_id=1, created_at=0.0)
