from pathlib import Path

import pytest

from snitchbot.sidecar.telegram_io.domain.topic_mapping_vo import TopicMappingVO
from snitchbot.sidecar.telegram_io.ports.driven.persistence.topic_store_json import (
    JsonFileTopicStore,
)


class TestJsonFileTopicStoreRoundtrip:
    def test_load_returns_empty_when_file_missing(self, tmp_path: Path):
        """Given no file, When load(), Then []."""
        store = JsonFileTopicStore(tmp_path / "topics.json")
        assert store.load() == []

    def test_save_then_load_roundtrip(self, tmp_path: Path):
        """Given a list of mappings, When save+load, Then preserved exactly."""
        store = JsonFileTopicStore(tmp_path / "topics.json")
        mappings = [
            TopicMappingVO(service="a", message_thread_id=10, created_at=1.5),
            TopicMappingVO(service="b", message_thread_id=20, created_at=2.5),
        ]
        store.save(mappings)
        loaded = store.load()
        assert loaded == mappings

    def test_save_uses_atomic_rename(self, tmp_path: Path):
        """After save, no .tmp file is left in the directory."""
        path = tmp_path / "topics.json"
        store = JsonFileTopicStore(path)
        store.save([TopicMappingVO(service="a", message_thread_id=1, created_at=0.0)])
        assert path.exists()
        assert not (path.parent / "topics.json.tmp").exists()

    def test_corrupted_file_returns_empty_and_removes_file(self, tmp_path: Path):
        path = tmp_path / "topics.json"
        path.write_text("not-json", encoding="utf-8")
        store = JsonFileTopicStore(path)
        assert store.load() == []
        assert not path.exists()

    def test_save_creates_parent_directory(self, tmp_path: Path):
        path = tmp_path / "deep" / "nested" / "topics.json"
        store = JsonFileTopicStore(path)
        store.save([TopicMappingVO(service="x", message_thread_id=1, created_at=0.0)])
        assert path.exists()
