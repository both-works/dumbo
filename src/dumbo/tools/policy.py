from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from dumbo.config import DumboConfig
from dumbo.tools.base import BaseTool, RiskLevel


class PolicyAction(StrEnum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    BLOCK = "block"


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction
    reason: str
    effective_risk: RiskLevel

    @property
    def allowed(self) -> bool:
        return self.action == PolicyAction.ALLOW

    @property
    def needs_confirmation(self) -> bool:
        return self.action == PolicyAction.REQUIRE_CONFIRMATION


class PolicyEngine:
    def __init__(self, config: DumboConfig):
        self.config = config

    def assess(self, tool: BaseTool, args: dict[str, Any]) -> PolicyDecision:
        risk = self._effective_risk(tool, args)

        if risk == RiskLevel.READ_ONLY:
            return PolicyDecision(PolicyAction.ALLOW, "Read-only action within policy.", risk)
        if risk == RiskLevel.LOW_RISK_OPEN:
            return PolicyDecision(PolicyAction.ALLOW, "Low-risk open action is allowed.", risk)
        if risk == RiskLevel.WRITE_SAFE:
            if getattr(tool, "always_requires_confirmation", False):
                return PolicyDecision(
                    PolicyAction.REQUIRE_CONFIRMATION,
                    "This write-capable action always requires confirmation.",
                    risk,
                )
            if self.config.app.trusted_mode and getattr(tool, "trusted_mode_can_allow", True):
                return PolicyDecision(PolicyAction.ALLOW, "Trusted mode allows safe writes.", risk)
            return PolicyDecision(
                PolicyAction.REQUIRE_CONFIRMATION, "Write action requires confirmation.", risk
            )
        if risk == RiskLevel.SHELL:
            return PolicyDecision(
                PolicyAction.REQUIRE_CONFIRMATION,
                "Shell command requires explicit confirmation.",
                risk,
            )
        if risk == RiskLevel.DESTRUCTIVE:
            return PolicyDecision(
                PolicyAction.REQUIRE_CONFIRMATION,
                "Destructive action requires explicit confirmation and impact review.",
                risk,
            )
        if risk == RiskLevel.PRIVILEGED:
            if not self.config.app.enable_privileged_tools:
                return PolicyDecision(
                    PolicyAction.BLOCK,
                    "Privileged tools are disabled in config.",
                    risk,
                )
            return PolicyDecision(
                PolicyAction.REQUIRE_CONFIRMATION,
                "Privileged action requires explicit confirmation.",
                risk,
            )
        return PolicyDecision(
            PolicyAction.REQUIRE_CONFIRMATION,
            "External commitment requires final user confirmation.",
            risk,
        )

    def _effective_risk(self, tool: BaseTool, args: dict[str, Any]) -> RiskLevel:
        classifier = getattr(tool, "classify_risk", None)
        if callable(classifier):
            return classifier(args)
        return tool.risk_level
