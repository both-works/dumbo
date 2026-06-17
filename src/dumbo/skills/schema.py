from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dumbo.tools.base import RiskLevel
from dumbo.tools.registry import ToolRegistry


@dataclass(frozen=True)
class SkillStep:
    tool: str
    args: dict[str, Any]


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    intent_examples: tuple[str, ...]
    steps: tuple[SkillStep, ...]
    risk_level: RiskLevel

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "intent_examples": list(self.intent_examples),
            "risk_level": self.risk_level.value,
            "steps": [{"tool": step.tool, "args": step.args} for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillDefinition:
        steps_data = data.get("steps", [])
        if not isinstance(steps_data, list) or not steps_data:
            raise ValueError("Skill requires at least one step")
        steps = []
        for item in steps_data:
            if not isinstance(item, dict) or "tool" not in item or "args" not in item:
                raise ValueError("Each skill step requires tool and args")
            if not isinstance(item["args"], dict):
                raise ValueError("Skill step args must be an object")
            steps.append(SkillStep(tool=str(item["tool"]), args=item["args"]))
        return cls(
            name=str(data["name"]),
            description=str(data.get("description", "")),
            intent_examples=tuple(str(item) for item in data.get("intent_examples", [])),
            steps=tuple(steps),
            risk_level=RiskLevel(str(data.get("risk_level", RiskLevel.WRITE_SAFE.value))),
        )


def load_skill(path: Path) -> SkillDefinition:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Skill file must contain a mapping: {path}")
    return SkillDefinition.from_dict(data)


def dump_skill(path: Path, skill: SkillDefinition) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(skill.to_dict(), handle, sort_keys=False)


@dataclass
class SkillBuilder:
    name: str
    description: str
    intent_examples: list[str] = field(default_factory=list)
    steps: list[SkillStep] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.WRITE_SAFE

    def add_step(self, tool: str, args: dict[str, Any]) -> None:
        self.steps.append(SkillStep(tool=tool, args=args))

    def build(self) -> SkillDefinition:
        return SkillDefinition(
            name=self.name,
            description=self.description,
            intent_examples=tuple(self.intent_examples),
            steps=tuple(self.steps),
            risk_level=self.risk_level,
        )


def validate_skill_against_registry(skill: SkillDefinition, registry: ToolRegistry) -> None:
    for step in skill.steps:
        tool = registry.get(step.tool)
        tool.validate_args(step.args)
