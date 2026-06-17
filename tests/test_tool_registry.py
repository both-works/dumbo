import pytest

from dumbo.tools.base import BaseTool
from dumbo.tools.registry import ToolRegistry


class DemoTool(BaseTool):
    name = "demo"
    description = "Demo tool"


def test_registry_registers_and_lists_tool() -> None:
    registry = ToolRegistry([DemoTool()])
    assert registry.names() == ["demo"]
    assert registry.get("demo").name == "demo"
    assert registry.tool_schemas()[0]["function"]["name"] == "demo"


def test_registry_rejects_duplicate_tool() -> None:
    registry = ToolRegistry([DemoTool()])
    with pytest.raises(ValueError):
        registry.register(DemoTool())
