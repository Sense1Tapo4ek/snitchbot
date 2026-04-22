"""ITopicStore — driven port for persisting service<->thread_id mappings.

Layer: app/interfaces (Protocol). Concrete implementation in
ports/driven/persistence/topic_store_json.py.
"""
from typing import Protocol

from snitchbot.sidecar.telegram_io.domain.topic_mapping_vo import TopicMappingVO


class ITopicStore(Protocol):
    def load(self) -> list[TopicMappingVO]: ...
    def save(self, mappings: list[TopicMappingVO]) -> None: ...
