from __future__ import annotations

from collections.abc import Iterable

from dumbo.tools.base import BaseTool


class ToolRegistry:
    def __init__(self, tools: Iterable[BaseTool] | None = None):
        self._tools: dict[str, BaseTool] = {}
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        if not tool.name:
            raise ValueError("Tool name is required")
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"Unknown tool: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self._tools)

    def tools(self) -> list[BaseTool]:
        return [self._tools[name] for name in self.names()]

    def tool_schemas(self) -> list[dict]:
        return [tool.tool_schema() for tool in self.tools()]
