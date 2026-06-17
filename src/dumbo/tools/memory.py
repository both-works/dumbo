from __future__ import annotations

from dataclasses import asdict
from typing import Any

from dumbo.memory.sqlite_store import SQLiteMemoryStore
from dumbo.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult


class RememberFactTool(BaseTool):
    name = "remember_fact"
    description = "Store a non-secret user preference or fact in local SQLite memory."
    risk_level = RiskLevel.WRITE_SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
            "source": {"type": "string"},
        },
        "required": ["key", "value", "source"],
    }

    def __init__(self, store: SQLiteMemoryStore):
        self.store = store

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult.success(f"Would remember fact {args['key']}.")
        self.store.remember(args["key"], args["value"], args["source"])
        return ToolResult.success(f"Remembered {args['key']}.")


class RecallFactsTool(BaseTool):
    name = "recall_facts"
    description = "Search local inspectable memory facts by keyword."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["query"],
    }

    def __init__(self, store: SQLiteMemoryStore):
        self.store = store

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        facts = self.store.recall(args["query"], int(args.get("limit", 10)))
        return ToolResult.success(
            f"Recalled {len(facts)} matching facts.",
            {"facts": [asdict(fact) for fact in facts]},
        )


class ForgetFactTool(BaseTool):
    name = "forget_fact"
    description = "Delete a local memory fact by key."
    risk_level = RiskLevel.DESTRUCTIVE
    parameters_schema = {
        "type": "object",
        "properties": {"key": {"type": "string"}},
        "required": ["key"],
    }

    def __init__(self, store: SQLiteMemoryStore):
        self.store = store

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult.success(f"Would forget fact {args['key']}.")
        deleted = self.store.forget(args["key"])
        return ToolResult.success("Forgot fact." if deleted else "No matching fact existed.")


class ListMemoryTool(BaseTool):
    name = "list_memory"
    description = "List all local memory facts."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self, store: SQLiteMemoryStore):
        self.store = store

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        facts = self.store.list_facts()
        return ToolResult.success(
            f"Listed {len(facts)} memory facts.",
            {"facts": [asdict(fact) for fact in facts]},
        )


def memory_tools(store: SQLiteMemoryStore) -> list[BaseTool]:
    return [
        RememberFactTool(store),
        RecallFactsTool(store),
        ForgetFactTool(store),
        ListMemoryTool(store),
    ]
