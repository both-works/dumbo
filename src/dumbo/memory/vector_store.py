from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VectorMatch:
    key: str
    text: str
    score: float


class SQLiteVectorStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS vectors (
                    key TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    vector_json TEXT NOT NULL
                )
                """
            )

    def upsert(self, key: str, text: str, vector: list[float]) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                INSERT INTO vectors (key, text, vector_json)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    text = excluded.text,
                    vector_json = excluded.vector_json
                """,
                (key, text, json.dumps(vector)),
            )

    def search(self, vector: list[float], limit: int = 10) -> list[VectorMatch]:
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT key, text, vector_json FROM vectors").fetchall()
        matches = [
            VectorMatch(key=row[0], text=row[1], score=_cosine(vector, json.loads(row[2])))
            for row in rows
        ]
        return sorted(matches, key=lambda match: match.score, reverse=True)[:limit]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
