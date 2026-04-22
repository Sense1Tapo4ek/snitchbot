"""JSON file topic store — atomic-rename persistence (mirrors mute_repo_json.py).

Layer: ports/driven (stdlib + json + pathlib).

Format: list of {"service": str, "message_thread_id": int, "created_at": float}.
"""
import json
import logging
from pathlib import Path

from snitchbot.sidecar.telegram_io.domain.topic_mapping_vo import TopicMappingVO

logger = logging.getLogger("snitchbot.sidecar.topic_store")

__all__ = ["JsonFileTopicStore"]


class JsonFileTopicStore:
    """Atomic JSON persistence for service<->thread_id mappings."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> list[TopicMappingVO]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [
                TopicMappingVO(
                    service=e["service"],
                    message_thread_id=int(e["message_thread_id"]),
                    created_at=float(e["created_at"]),
                )
                for e in data
            ]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            logger.warning("corrupted topic store %r, removing.", self._path)
            self._path.unlink(missing_ok=True)
            return []

    def save(self, mappings: list[TopicMappingVO]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "service": m.service,
                "message_thread_id": m.message_thread_id,
                "created_at": m.created_at,
            }
            for m in mappings
        ]
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.rename(self._path)
