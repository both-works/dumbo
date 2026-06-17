from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from dumbo.tools.audit import redact
from dumbo.tools.base import RiskLevel, ToolResult


class ApprovalMode(StrEnum):
    NEVER = "NEVER"
    INTERACTIVE = "INTERACTIVE"
    ALLOW_LOW_RISK_ONLY = "ALLOW_LOW_RISK_ONLY"


@dataclass(frozen=True)
class ApprovalRequest:
    tool_name: str
    args: dict[str, Any]
    risk_level: RiskLevel
    policy_reason: str
    dry_run_result: ToolResult | None
    expected_impact: str
    rollback_notes: str


ApprovalCallback = Callable[[ApprovalRequest], bool]


def can_noninteractively_approve(
    mode: ApprovalMode,
    *,
    risk_level: RiskLevel,
    allow_noninteractive_approval: bool,
) -> bool:
    if mode != ApprovalMode.ALLOW_LOW_RISK_ONLY:
        return False
    if not allow_noninteractive_approval:
        return False
    return risk_level == RiskLevel.WRITE_SAFE


def prompt_for_approval(request: ApprovalRequest) -> bool:
    redacted_args = json.dumps(redact(request.args), ensure_ascii=True, sort_keys=True)
    print("Confirmation required:")
    print(f"- Tool: {request.tool_name}")
    print(f"- Args: {redacted_args}")
    print(f"- Risk: {request.risk_level.value}")
    print(f"- Policy reason: {request.policy_reason}")
    if request.dry_run_result is None:
        print("- Dry run: unavailable")
    else:
        dry_run = {
            "ok": request.dry_run_result.ok,
            "message": request.dry_run_result.message,
            "data": redact(request.dry_run_result.data),
            "error": request.dry_run_result.error,
        }
        print(f"- Dry run: {json.dumps(dry_run, ensure_ascii=True, sort_keys=True)}")
    print(f"- Expected impact: {request.expected_impact}")
    print(f"- Rollback notes: {request.rollback_notes}")
    return input("Approve? y/N: ").strip().casefold() == "y"
