from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dumbo.tools.policy import PolicyDecision

SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|authorization|cookie|credential|private[_-]?key)",
    re.IGNORECASE,
)
SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})"
)


class AuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    user_request TEXT NOT NULL,
                    model TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    dry_run_json TEXT,
                    policy_action TEXT NOT NULL,
                    policy_reason TEXT NOT NULL,
                    risk_level TEXT NOT NULL,
                    result_json TEXT,
                    error TEXT
                )
                """
            )

    def log_tool_call(
        self,
        *,
        user_request: str,
        model: str,
        tool_name: str,
        args: dict[str, Any],
        decision: PolicyDecision,
        dry_run_result: Any | None = None,
        result: Any | None = None,
        error: str | None = None,
    ) -> int:
        timestamp = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO tool_calls (
                    timestamp, user_request, model, tool_name, args_json, dry_run_json,
                    policy_action, policy_reason, risk_level, result_json, error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    user_request,
                    model,
                    tool_name,
                    _json(redact(args)),
                    _json(redact(_to_jsonable(dry_run_result)))
                    if dry_run_result is not None
                    else None,
                    decision.action.value,
                    decision.reason,
                    decision.effective_risk.value,
                    _json(redact(_to_jsonable(result))) if result is not None else None,
                    _redact_string(error) if error else None,
                ),
            )
            return int(cursor.lastrowid)

    def tail(self, limit: int = 20) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT * FROM tool_calls
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def _redact_string(value: str) -> str:
    return SECRET_VALUE_RE.sub("[REDACTED]", value)


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)[:20000]
