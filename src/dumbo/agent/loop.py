from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Protocol

from dumbo.agent.approval import (
    ApprovalCallback,
    ApprovalMode,
    ApprovalRequest,
    can_noninteractively_approve,
)
from dumbo.agent.ollama_client import OllamaClient, OllamaError
from dumbo.agent.prompts import build_system_prompt
from dumbo.agent.schemas import AgentResponse, ToolCall
from dumbo.config import DumboConfig, ModelProfile
from dumbo.memory.sqlite_store import SQLiteMemoryStore
from dumbo.tools.audit import AuditLog
from dumbo.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from dumbo.tools.policy import PolicyAction, PolicyEngine
from dumbo.tools.registry import ToolRegistry


class ChatClient(Protocol):
    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        format_value: str | dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


MAX_LIST_ENTRIES_IN_REPLY = 40


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, policy: PolicyEngine, audit: AuditLog):
        self.registry = registry
        self.policy = policy
        self.audit = audit

    def execute_tool(
        self,
        name: str,
        args: dict[str, Any],
        context: ToolContext,
        *,
        approval_mode: ApprovalMode = ApprovalMode.NEVER,
        approval_callback: ApprovalCallback | None = None,
    ) -> ToolResult:
        try:
            tool = self.registry.get(name)
        except KeyError as exc:
            tool = _UnknownTool(name)
            decision = self.policy.assess(tool, args)
            result = ToolResult.failure(f"Unknown tool blocked: {name}", error=str(exc))
            self._audit(tool, args, context, decision, None, result)
            return result

        decision = self.policy.assess(tool, args)
        try:
            tool.validate_args(args)
        except Exception as exc:
            result = ToolResult.failure(f"Tool {name} arguments were rejected.", error=str(exc))
            self._audit(tool, args, context, decision, None, result)
            return result

        dry_run = None
        if tool.dry_run_supported:
            try:
                dry_run = tool.dry_run(args, context)
            except Exception as exc:
                result = ToolResult.failure(f"Tool {name} dry run failed.", error=str(exc))
                self._audit(tool, args, context, decision, None, result)
                return result

        if decision.action == PolicyAction.BLOCK:
            result = ToolResult.failure(f"Blocked by policy: {decision.reason}")
            self._audit(tool, args, context, decision, dry_run, result)
            return result

        if decision.action == PolicyAction.REQUIRE_CONFIRMATION:
            approved = can_noninteractively_approve(
                approval_mode,
                risk_level=decision.effective_risk,
                allow_noninteractive_approval=getattr(tool, "allow_noninteractive_approval", True),
            )
            if not approved and approval_mode == ApprovalMode.INTERACTIVE:
                request = ApprovalRequest(
                    tool_name=tool.name,
                    args=args,
                    risk_level=decision.effective_risk,
                    policy_reason=decision.reason,
                    dry_run_result=dry_run,
                    expected_impact=tool.expected_impact(args),
                    rollback_notes=tool.rollback_notes(args),
                )
                approved = approval_callback(request) if approval_callback else False
            if not approved:
                result = ToolResult.failure(f"Confirmation required: {decision.reason}")
                self._audit(tool, args, context, decision, dry_run, result)
                return result

        try:
            result = tool.execute(args, context)
        except Exception as exc:
            result = ToolResult.failure(f"Tool {name} failed.", error=str(exc))
        self._audit(tool, args, context, decision, dry_run, result)
        return result

    def _audit(
        self,
        tool: BaseTool,
        args: dict[str, Any],
        context: ToolContext,
        decision: Any,
        dry_run: ToolResult | None,
        result: ToolResult,
    ) -> None:
        self.audit.log_tool_call(
            user_request=context.user_request,
            model=context.model,
            tool_name=tool.name,
            args=args,
            decision=decision,
            dry_run_result=asdict(dry_run) if dry_run else None,
            result=asdict(result),
            error=result.error,
        )


class AgentLoop:
    def __init__(
        self,
        *,
        config: DumboConfig,
        profile: ModelProfile,
        registry: ToolRegistry,
        policy: PolicyEngine,
        audit: AuditLog,
        ollama: ChatClient | OllamaClient,
        memory_store: SQLiteMemoryStore | None = None,
        approval_callback: ApprovalCallback | None = None,
    ):
        self.config = config
        self.profile = profile
        self.registry = registry
        self.executor = ToolExecutor(registry, policy, audit)
        self.ollama = ollama
        self.memory_store = memory_store
        self.approval_callback = approval_callback

    def run(
        self,
        user_input: str,
        *,
        approval_mode: ApprovalMode = ApprovalMode.INTERACTIVE,
        prefer_ollama: bool = True,
    ) -> AgentResponse:
        context = ToolContext(
            user_request=user_input,
            model=self.profile.planner_model,
            timeout_seconds=self.config.app.tool_timeout_seconds,
        )

        local_answer = parse_local_answer(user_input, self.config)
        if local_answer is not None:
            return AgentResponse(final_text=local_answer, stopped_reason="local_answer")

        local_call = parse_local_intent(user_input)
        if local_call is not None:
            result = self.executor.execute_tool(
                local_call.name,
                local_call.args,
                context,
                approval_mode=approval_mode,
                approval_callback=self.approval_callback,
            )
            return AgentResponse(
                final_text=_summarize_tool_result(local_call.name, result, local_call.args),
                tool_results=[asdict(result)],
                stopped_reason="local_intent",
            )

        if not prefer_ollama:
            return AgentResponse(
                final_text="No deterministic local intent matched, and model use is disabled.",
                stopped_reason="no_model",
            )

        messages = [
            {
                "role": "system",
                "content": build_system_prompt(
                    self.config,
                    self.profile,
                    self.registry,
                    memory_context=self._memory_context(user_input),
                ),
            },
            {"role": "user", "content": user_input},
        ]
        tools_enabled = should_enable_tools(user_input)
        tool_results: list[dict[str, Any]] = []
        for _ in range(self.config.app.max_tool_calls_per_request):
            try:
                chat_args: dict[str, Any] = {
                    "model": self.profile.planner_model,
                    "messages": messages,
                    "stream": False,
                }
                if tools_enabled:
                    chat_args["tools"] = self.registry.tool_schemas()
                options = self._ollama_options()
                if options:
                    chat_args["options"] = options
                response = self.ollama.chat(**chat_args)
            except OllamaError as exc:
                return AgentResponse(
                    final_text=f"Ollama is unavailable: {exc}",
                    tool_results=tool_results,
                    stopped_reason="ollama_unavailable",
                )

            message = response.get("message", {})
            calls = parse_tool_calls(message)
            if not calls:
                content = str(message.get("content", "")).strip()
                return AgentResponse(
                    final_text=content or "The model returned no final answer.",
                    tool_results=tool_results,
                )

            messages.append(message)
            for call in calls:
                result = self.executor.execute_tool(
                    call.name,
                    call.args,
                    context,
                    approval_mode=approval_mode,
                    approval_callback=self.approval_callback,
                )
                result_dict = asdict(result)
                tool_results.append(result_dict)
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": call.name,
                        "content": json.dumps(result_dict, ensure_ascii=True),
                    }
                )
                if not result.ok:
                    return AgentResponse(
                        final_text=_summarize_tool_result(call.name, result, call.args),
                        tool_results=tool_results,
                        stopped_reason="tool_blocked_or_failed",
                    )

        return AgentResponse(
            final_text="Stopped after reaching the maximum tool-call count.",
            tool_results=tool_results,
            stopped_reason="max_steps",
        )

    def _memory_context(self, user_input: str) -> str:
        if self.memory_store is None:
            return ""
        from dumbo.agent.memory_context import build_memory_context

        return build_memory_context(self.memory_store, user_input)

    def _ollama_options(self) -> dict[str, Any]:
        context_tokens = self.config.model.context_tokens
        if context_tokens is None and self.profile.name in {"recommended", "high_end"}:
            context_tokens = 64000
        if context_tokens is None:
            return {}
        return {"num_ctx": context_tokens}


def parse_tool_calls(message: dict[str, Any]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for item in message.get("tool_calls") or []:
        function = item.get("function", item)
        name = function.get("name")
        args = function.get("arguments", {})
        if isinstance(args, str):
            args = json.loads(args)
        if isinstance(name, str) and isinstance(args, dict):
            calls.append(ToolCall(name=name, args=args))
    if calls:
        return calls

    content = str(message.get("content", "")).strip()
    if not content:
        return []
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict) and "tool" in payload:
        payload = [payload]
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and isinstance(item.get("tool"), str):
                args = item.get("args", {})
                if isinstance(args, dict):
                    calls.append(ToolCall(name=item["tool"], args=args))
    return calls


def parse_local_intent(user_input: str) -> ToolCall | None:
    text = user_input.strip()
    lowered = text.casefold()
    home = Path.home()
    windows_path = _extract_windows_path(text)

    if "allowed roots" in lowered or "filesystem roots" in lowered:
        return ToolCall("list_allowed_roots", {})
    if windows_path and re.search(r"\b(list|show)\b|\bwhat(?:'s| is)\b.*\b(in|inside)\b", lowered):
        return ToolCall("list_dir", {"path": windows_path})
    if re.search(r"\b(list|show)\b.*\bdownloads\b", lowered) or re.search(
        r"\bwhat(?:'s| is)\b.*\b(in|inside)\b.*\bdownloads\b", lowered
    ):
        return ToolCall("list_dir", {"path": str(home / "Downloads")})
    if re.search(r"\b(list|show)\b.*\bdocuments\b", lowered) or re.search(
        r"\bwhat(?:'s| is)\b.*\b(in|inside)\b.*\bdocuments\b", lowered
    ):
        return ToolCall("list_dir", {"path": str(home / "Documents")})
    if re.search(r"\bopen\b.*\bnotepad\b", lowered):
        return ToolCall("open_app", {"name_or_path": "notepad"})
    open_match = re.match(r"open\s+(?:app\s+)?(.+?)\s*$", text, flags=re.IGNORECASE)
    if open_match:
        target = _normalise_open_target(open_match.group(1).strip().rstrip("."))
        if target and not _extract_windows_path(target):
            return ToolCall("open_app", {"name_or_path": target})
    if lowered.startswith("run powershell "):
        return ToolCall("run_powershell", {"command": text[len("run powershell ") :]})
    if "search" in lowered and "documents" in lowered:
        extensions = []
        if "pdf" in lowered:
            extensions.append("pdf")
        query_match = re.search(r"\bnamed\s+([A-Za-z0-9_.-]+)", text, flags=re.IGNORECASE)
        query = query_match.group(1) if query_match else ""
        return ToolCall(
            "search_files",
            {
                "query": query,
                "roots": [str(home / "Documents")],
                "extensions": extensions,
                "max_results": 50,
            },
        )
    if lowered.startswith("delete this file "):
        return ToolCall("delete_file", {"path": text[len("delete this file ") :].strip()})
    return None


def parse_local_answer(user_input: str, config: DumboConfig) -> str | None:
    text = " ".join(user_input.strip().split())
    lowered = text.casefold().rstrip("?! .")
    if lowered in {"who are you", "what are you", "what is dumbo", "who is dumbo"}:
        return (
            "I'm Dumbo, your local desktop assistant. I run on this PC, use the local "
            "Ollama model, and can help with conversation, files, apps, browser/desktop "
            "automation, memory, and PowerShell through audited tools."
        )
    if lowered in {"what can you do", "what can dumbo do", "help", "show help"}:
        roots = ", ".join(str(root) for root in config.allowed_roots)
        return (
            "I can answer questions, open apps like Chrome or Word, inspect and manage files, "
            "search your drives, remember facts, use browser and desktop automation, and run "
            "PowerShell when you approve it. Current filesystem roots: "
            f"{roots}."
        )
    return None


def should_enable_tools(user_input: str) -> bool:
    lowered = user_input.casefold()
    if _extract_windows_path(user_input):
        return True
    action_patterns = [
        r"\b(open|launch|start|close|focus)\b",
        r"\b(list|show|read|search|find|scan)\b.*\b(file|folder|directory|drive|download|document|root)\b",
        r"\bwhat(?:'s| is)\b.*\b(in|inside)\b.*\b(downloads|documents|folder|directory|drive)\b",
        r"\b(create|write|save|append|overwrite|move|rename|delete|remove)\b",
        r"\b(run|execute)\b.*\b(powershell|command|script)\b",
        r"\bpowershell\b",
        r"\b(click|type|press|hotkey|screenshot)\b",
        r"\bremember\b|\bforget\b|\bmemory\b",
        r"\bgo to\b.*\bhttps?://",
        r"https?://",
    ]
    return any(re.search(pattern, lowered) for pattern in action_patterns)


def _normalise_open_target(target: str) -> str:
    lowered = " ".join(target.casefold().split())
    replacements = {
        "a word document": "word",
        "word document": "word",
        "new word document": "word",
        "a microsoft word document": "word",
        "microsoft word document": "word",
        "a spreadsheet": "excel",
        "spreadsheet": "excel",
        "an excel spreadsheet": "excel",
        "excel spreadsheet": "excel",
        "a presentation": "powerpoint",
        "presentation": "powerpoint",
        "a powerpoint presentation": "powerpoint",
        "powerpoint presentation": "powerpoint",
        "browser": "chrome",
        "a browser": "chrome",
        "web browser": "chrome",
    }
    if lowered in replacements:
        return replacements[lowered]
    for article in ("a ", "an ", "the "):
        if lowered.startswith(article):
            lowered = lowered[len(article) :]
            break
    return lowered


def _extract_windows_path(text: str) -> str | None:
    quoted = re.search(r"""["']([A-Za-z]:[\\/][^"']+)["']""", text)
    match = quoted or re.search(r"([A-Za-z]:[\\/][^\r\n\"']*)", text)
    if match is None:
        return None
    candidate = match.group(1).strip()
    for marker in [". Reply", ". reply", "\n"]:
        index = candidate.find(marker)
        if index >= 0:
            candidate = candidate[:index]
    candidate = candidate.rstrip(" .")
    return candidate or None


def _summarize_tool_result(
    tool_name: str, result: ToolResult, args: dict[str, Any] | None = None
) -> str:
    if result.ok and tool_name == "list_allowed_roots":
        roots = result.data.get("roots", [])
        if isinstance(roots, list):
            return "\n".join(str(root) for root in roots)
    if result.ok and tool_name == "list_dir":
        entries = result.data.get("entries", [])
        if isinstance(entries, list):
            names = [str(entry.get("name", "")) for entry in entries if entry.get("name")]
            visible = names[:MAX_LIST_ENTRIES_IN_REPLY]
            if len(names) > MAX_LIST_ENTRIES_IN_REPLY:
                visible.append(f"... and {len(names) - MAX_LIST_ENTRIES_IN_REPLY} more.")
            return "\n".join(visible)
    if tool_name == "open_app":
        target = _display_target(args, result)
        if result.ok:
            return f"Opened {target}."
        if result.error and "Confirmation required" in result.error:
            return f"I did not open {target} because approval was not granted."
        return f"I could not open {target}: {result.error or result.message}"
    if result.ok:
        return result.message
    return result.message + (f" Error: {result.error}" if result.error else "")


def _display_target(args: dict[str, Any] | None, result: ToolResult) -> str:
    if args and args.get("name_or_path"):
        return str(args["name_or_path"]).strip()
    if result.data.get("target"):
        return str(result.data["target"]).strip()
    return "the app"


class _UnknownTool(BaseTool):
    def __init__(self, name: str):
        self.name = name
        self.description = f"Blocked unknown tool request for {name}"
        self.risk_level = RiskLevel.PRIVILEGED
