"""TopicMappingVO — service <-> message_thread_id binding (Invariant F2)."""
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class TopicMappingVO:
    service: str
    message_thread_id: int
    created_at: float

    def __post_init__(self) -> None:
        if not self.service:
            raise ValueError("service must be a non-empty string")
        if self.message_thread_id <= 0:
            raise ValueError("message_thread_id must be a positive integer")
