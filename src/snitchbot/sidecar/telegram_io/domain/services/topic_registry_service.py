"""TopicRegistry — in-memory bidirectional service<->thread map (Invariant F2).

Layer: domain (stdlib only).
"""
from snitchbot.sidecar.telegram_io.domain.topic_mapping_vo import TopicMappingVO


class TopicRegistry:
    def __init__(self) -> None:
        self._by_service: dict[str, TopicMappingVO] = {}
        self._by_thread: dict[int, str] = {}

    def lookup(self, service: str) -> TopicMappingVO | None:
        return self._by_service.get(service)

    def reverse_lookup(self, message_thread_id: int) -> str | None:
        return self._by_thread.get(message_thread_id)

    def register(self, mapping: TopicMappingVO) -> None:
        prev = self._by_service.get(mapping.service)
        if prev is not None:
            self._by_thread.pop(prev.message_thread_id, None)
        self._by_service[mapping.service] = mapping
        self._by_thread[mapping.message_thread_id] = mapping.service

    def forget(self, service: str) -> None:
        prev = self._by_service.pop(service, None)
        if prev is not None:
            self._by_thread.pop(prev.message_thread_id, None)

    def snapshot(self) -> tuple[TopicMappingVO, ...]:
        return tuple(self._by_service.values())

    def bulk_load(self, mappings: list[TopicMappingVO]) -> None:
        self._by_service.clear()
        self._by_thread.clear()
        for m in mappings:
            self.register(m)
