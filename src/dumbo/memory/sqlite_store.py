from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from dumbo.tools.audit import redact

SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|credential|private[_-]?key|cookie|wallet)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MemoryFact:
    key: str
    value: str
    source: str
    created_at: str
    updated_at: str


class SQLiteMemoryStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS facts (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def remember(self, key: str, value: str, source: str) -> None:
        if _looks_sensitive_key(key) or _looks_sensitive_value(value):
            raise ValueError("Refusing to store likely secret material in memory.")
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO facts (key, value, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    source = excluded.source,
                    updated_at = excluded.updated_at
                """,
                (key, value, source, now, now),
            )

    def list_facts(self) -> list[MemoryFact]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                "SELECT key, value, source, created_at, updated_at FROM facts ORDER BY key"
            ).fetchall()
        return [MemoryFact(*row) for row in rows]

    def recall(self, query: str, limit: int = 10) -> list[MemoryFact]:
        pattern = f"%{query}%"
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute(
                """
                SELECT key, value, source, created_at, updated_at
                FROM facts
                WHERE key LIKE ? OR value LIKE ? OR source LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (pattern, pattern, pattern, limit),
            ).fetchall()
        return [MemoryFact(*row) for row in rows]

    def forget(self, key: str) -> bool:
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute("DELETE FROM facts WHERE key = ?", (key,))
            return cursor.rowcount > 0


def _looks_sensitive_key(value: str) -> bool:
    return SECRET_KEY_RE.search(value) is not None


def _looks_sensitive_value(value: str) -> bool:
    return redact(value) != value
