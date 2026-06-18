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
    print("Confirmation required:")
    print(f"- Action: {request.expected_impact}")
    print(f"- Risk: {request.risk_level.value}")
    print(f"- Reason: {request.policy_reason}")
    redacted_args = redact(request.args)
    if request.tool_name == "run_powershell" and isinstance(redacted_args, dict):
        command = redacted_args.get("command")
        if command:
            print(f"- Command: {command}")
    elif request.risk_level not in {RiskLevel.WRITE_SAFE, RiskLevel.LOW_RISK_OPEN}:
        print(f"- Inputs: {json.dumps(redacted_args, ensure_ascii=True, sort_keys=True)}")
    if request.dry_run_result is not None and request.dry_run_result.message:
        print(f"- Preview: {request.dry_run_result.message}")
    if request.rollback_notes != "No automatic rollback is available.":
        print(f"- Rollback: {request.rollback_notes}")
    return input("Approve? y/N: ").strip().casefold() == "y"
