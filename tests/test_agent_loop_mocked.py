from pathlib import Path
from typing import Any

from dumbo.agent.loop import AgentLoop, parse_local_intent
from dumbo.config import DumboConfig, FilesystemConfig, ModelProfile
from dumbo.tools.audit import AuditLog
from dumbo.tools.filesystem import ListDirTool
from dumbo.tools.policy import PolicyEngine
from dumbo.tools.registry import ToolRegistry


class FakeChatClient:
    def __init__(self, path: Path):
        self.path = path
        self.calls = 0

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        format_value: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "list_dir",
                                "arguments": {"path": str(self.path)},
                            }
                        }
                    ],
                }
            }
        return {"message": {"role": "assistant", "content": "done"}}


def test_agent_loop_executes_mocked_tool_call(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    config = DumboConfig(filesystem=FilesystemConfig(project_roots=(tmp_path.resolve(),)))
    profile = ModelProfile(
        name="test",
        planner_model="mock",
        vision_model="mock-v",
        embedding_model="mock-e",
        stt_model="none",
        tts_engine="none",
    )
    registry = ToolRegistry([ListDirTool(config)])
    audit = AuditLog(tmp_path / "audit.sqlite3")
    agent = AgentLoop(
        config=config,
        profile=profile,
        registry=registry,
        policy=PolicyEngine(config),
        audit=audit,
        ollama=FakeChatClient(tmp_path),
    )

    response = agent.run("what files are there?")
    assert response.final_text == "done"
    assert response.tool_results[0]["ok"] is True
    assert audit.tail(1)[0]["tool_name"] == "list_dir"


def test_local_list_dir_response_includes_entry_names(tmp_path: Path) -> None:
    (tmp_path / "visible.txt").write_text("ok", encoding="utf-8")
    config = DumboConfig(filesystem=FilesystemConfig(project_roots=(tmp_path.resolve(),)))
    profile = ModelProfile(
        name="test",
        planner_model="mock",
        vision_model="mock-v",
        embedding_model="mock-e",
        stt_model="none",
        tts_engine="none",
    )
    audit = AuditLog(tmp_path / "audit.sqlite3")
    agent = AgentLoop(
        config=config,
        profile=profile,
        registry=ToolRegistry([ListDirTool(config)]),
        policy=PolicyEngine(config),
        audit=audit,
        ollama=FakeChatClient(tmp_path),
    )

    response = agent.run(f"list {tmp_path}", prefer_ollama=False)
    assert "visible.txt" in response.final_text.splitlines()


def test_parse_local_intent_lists_exact_windows_path() -> None:
    call = parse_local_intent(
        "Use the filesystem tool to list the top-level entries in C:/both_/dumbo. "
        "Reply with only the entry names."
    )
    assert call is not None
    assert call.name == "list_dir"
    assert call.args == {"path": "C:/both_/dumbo"}


def test_parse_local_intent_opens_generic_app_name() -> None:
    call = parse_local_intent("open chrome")
    assert call is not None
    assert call.name == "open_app"
    assert call.args == {"name_or_path": "chrome"}


def test_parse_local_intent_lists_allowed_roots() -> None:
    call = parse_local_intent("list allowed roots")
    assert call is not None
    assert call.name == "list_allowed_roots"
    assert call.args == {}
