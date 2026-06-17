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
                final_text=_summarize_tool_result(local_call.name, result),
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
        tool_results: list[dict[str, Any]] = []
        for _ in range(self.config.app.max_tool_calls_per_request):
            try:
                chat_args: dict[str, Any] = {
                    "model": self.profile.planner_model,
                    "messages": messages,
                    "tools": self.registry.tool_schemas(),
                    "stream": False,
                }
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
                        final_text=_summarize_tool_result(call.name, result),
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

    if re.search(r"\blist\b.*\bdownloads\b", lowered):
        return ToolCall("list_dir", {"path": str(home / "Downloads")})
    if re.search(r"\blist\b.*\bdocuments\b", lowered):
        return ToolCall("list_dir", {"path": str(home / "Documents")})
    if re.search(r"\bopen\b.*\bnotepad\b", lowered):
        return ToolCall("open_app", {"name_or_path": "notepad"})
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


def _summarize_tool_result(tool_name: str, result: ToolResult) -> str:
    if result.ok:
        return f"{tool_name}: {result.message}"
    return f"{tool_name}: {result.message}" + (f" Error: {result.error}" if result.error else "")


class _UnknownTool(BaseTool):
    def __init__(self, name: str):
        self.name = name
        self.description = f"Blocked unknown tool request for {name}"
        self.risk_level = RiskLevel.PRIVILEGED
