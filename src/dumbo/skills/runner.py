from __future__ import annotations

import re
from typing import Any

from dumbo.agent.approval import ApprovalCallback, ApprovalMode
from dumbo.agent.loop import ToolExecutor
from dumbo.skills.schema import SkillDefinition
from dumbo.tools.base import ToolContext, ToolResult

PLACEHOLDER_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")


class SkillRunner:
    def __init__(self, executor: ToolExecutor):
        self.executor = executor

    def run(
        self,
        skill: SkillDefinition,
        context: ToolContext,
        *,
        placeholders: dict[str, str] | None = None,
        approval_mode: ApprovalMode = ApprovalMode.NEVER,
        approval_callback: ApprovalCallback | None = None,
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for step in skill.steps:
            try:
                step_args = substitute_placeholders(step.args, placeholders or {})
            except ValueError as exc:
                results.append(
                    ToolResult.failure("Skill placeholder substitution failed.", str(exc))
                )
                break
            result = self.executor.execute_tool(
                step.tool,
                step_args,
                context,
                approval_mode=approval_mode,
                approval_callback=approval_callback,
            )
            results.append(result)
            if not result.ok:
                break
        return results


def substitute_placeholders(value: Any, placeholders: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: substitute_placeholders(item, placeholders) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute_placeholders(item, placeholders) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in placeholders:
            raise ValueError(f"Missing skill argument: {key}")
        return placeholders[key]

    return PLACEHOLDER_RE.sub(replace, value)
