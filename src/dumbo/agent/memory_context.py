from __future__ import annotations

from dumbo.memory.sqlite_store import SQLiteMemoryStore
from dumbo.tools.audit import redact


def build_memory_context(store: SQLiteMemoryStore, user_input: str, limit: int = 5) -> str:
    query = " ".join(_keywords(user_input))
    if not query:
        return ""
    facts = store.recall(query, limit=limit)
    if not facts:
        return ""
    lines = []
    for fact in facts:
        safe_value = redact(fact.value)
        if safe_value != fact.value:
            continue
        lines.append(f"- {fact.key}: {safe_value} (source: {fact.source})")
    return "\n".join(lines)


def _keywords(text: str) -> list[str]:
    stop_words = {
        "a",
        "an",
        "and",
        "for",
        "in",
        "is",
        "it",
        "my",
        "of",
        "on",
        "the",
        "to",
    }
    words = []
    for raw in text.casefold().replace("_", " ").split():
        word = "".join(ch for ch in raw if ch.isalnum())
        if len(word) >= 3 and word not in stop_words:
            words.append(word)
    return words
