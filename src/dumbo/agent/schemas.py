from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class AgentResponse:
    final_text: str
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    stopped_reason: str = "final"
