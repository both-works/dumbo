from pathlib import Path
from typing import Any

from dumbo.agent.loop import (
    AgentLoop,
    parse_local_answer,
    parse_local_intent,
    should_enable_tools,
)
from dumbo.config import DumboConfig, FilesystemConfig, ModelProfile
from dumbo.tools.audit import AuditLog
from dumbo.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
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


class FakeOpenAppTool(BaseTool):
    name = "open_app"
    risk_level = RiskLevel.LOW_RISK_OPEN
    parameters_schema = {
        "type": "object",
        "properties": {"name_or_path": {"type": "string"}},
        "required": ["name_or_path"],
    }

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        return ToolResult.success("Opened app.", {"target": args["name_or_path"]})


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


def test_local_list_dir_response_is_limited(tmp_path: Path) -> None:
    for index in range(45):
        (tmp_path / f"item-{index:02}.txt").write_text("ok", encoding="utf-8")
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
    assert len(response.final_text.splitlines()) == 41
    assert response.final_text.splitlines()[-1].startswith("... and ")


def test_local_open_app_response_is_human_readable(tmp_path: Path) -> None:
    config = DumboConfig()
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
        registry=ToolRegistry([FakeOpenAppTool()]),
        policy=PolicyEngine(config),
        audit=audit,
        ollama=FakeChatClient(tmp_path),
    )

    response = agent.run("open word", prefer_ollama=False)
    assert response.final_text == "Opened word."


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


def test_parse_local_intent_understands_word_document_sentence() -> None:
    call = parse_local_intent("open a word document")
    assert call is not None
    assert call.name == "open_app"
    assert call.args == {"name_or_path": "word"}


def test_parse_local_intent_understands_natural_downloads_question() -> None:
    call = parse_local_intent("what's in my Downloads?")
    assert call is not None
    assert call.name == "list_dir"
    assert "Downloads" in str(call.args["path"])


def test_parse_local_intent_lists_allowed_roots() -> None:
    call = parse_local_intent("list allowed roots")
    assert call is not None
    assert call.name == "list_allowed_roots"
    assert call.args == {}


def test_identity_question_gets_direct_answer_without_tools() -> None:
    answer = parse_local_answer("who are you?", DumboConfig())
    assert answer is not None
    assert "Dumbo" in answer
    assert "local desktop assistant" in answer


def test_tools_are_not_enabled_for_general_conversation() -> None:
    assert not should_enable_tools("who are you?")
    assert not should_enable_tools("explain why the sky is blue")
    assert should_enable_tools("open a word document")
    assert should_enable_tools("what's in my Downloads?")
