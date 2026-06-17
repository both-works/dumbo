from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dumbo.skills.schema import SkillBuilder, SkillDefinition
from dumbo.tools.base import RiskLevel


@dataclass
class TeachRecorder:
    name: str
    description: str
    intent_examples: list[str] = field(default_factory=list)
    steps: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.READ_ONLY

    def record_tool_call(self, tool: str, args: dict[str, Any], risk_level: RiskLevel) -> None:
        self.steps.append((tool, args))
        self.risk_level = _max_risk(self.risk_level, risk_level)

    def build(self) -> SkillDefinition:
        builder = SkillBuilder(
            name=self.name,
            description=self.description,
            intent_examples=self.intent_examples,
            risk_level=self.risk_level,
        )
        for tool, args in self.steps:
            builder.add_step(tool, args)
        return builder.build()


def _max_risk(left: RiskLevel, right: RiskLevel) -> RiskLevel:
    order = [
        RiskLevel.READ_ONLY,
        RiskLevel.LOW_RISK_OPEN,
        RiskLevel.WRITE_SAFE,
        RiskLevel.SHELL,
        RiskLevel.DESTRUCTIVE,
        RiskLevel.PRIVILEGED,
        RiskLevel.EXTERNAL_COMMITMENT,
    ]
    return order[max(order.index(left), order.index(right))]
