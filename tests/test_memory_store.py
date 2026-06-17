from pathlib import Path

import pytest

from dumbo.memory.sqlite_store import SQLiteMemoryStore


def test_memory_store_remember_recall_forget(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    store.remember("preferred_editor", "notepad", "test")
    facts = store.recall("editor")
    assert len(facts) == 1
    assert facts[0].value == "notepad"
    assert store.forget("preferred_editor") is True
    assert store.list_facts() == []


def test_memory_store_rejects_likely_secret(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.sqlite3")
    with pytest.raises(ValueError):
        store.remember("api_key", "sk-thisisnotarealbutlongenoughkey", "test")
