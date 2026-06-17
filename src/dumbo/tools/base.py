from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RiskLevel(StrEnum):
    READ_ONLY = "READ_ONLY"
    LOW_RISK_OPEN = "LOW_RISK_OPEN"
    WRITE_SAFE = "WRITE_SAFE"
    SHELL = "SHELL"
    DESTRUCTIVE = "DESTRUCTIVE"
    PRIVILEGED = "PRIVILEGED"
    EXTERNAL_COMMITMENT = "EXTERNAL_COMMITMENT"


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @classmethod
    def success(cls, message: str, data: dict[str, Any] | None = None) -> ToolResult:
        return cls(ok=True, message=message, data=data or {})

    @classmethod
    def failure(cls, message: str, error: str | None = None) -> ToolResult:
        return cls(ok=False, message=message, error=error or message)


@dataclass
class ToolContext:
    user_request: str
    model: str
    dry_run: bool = False
    timeout_seconds: int = 30


class ToolValidationError(ValueError):
    pass


class BaseTool:
    name: str = ""
    description: str = ""
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    dry_run_supported: bool = False
    always_requires_confirmation: bool = False
    allow_noninteractive_approval: bool = True
    trusted_mode_can_allow: bool = True
    parameters_schema: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    def validate_args(self, args: dict[str, Any]) -> None:
        if not isinstance(args, dict):
            raise ToolValidationError(f"{self.name} arguments must be an object")

        required = self.parameters_schema.get("required", [])
        for key in required:
            if key not in args:
                raise ToolValidationError(f"{self.name} missing required argument: {key}")

        properties = self.parameters_schema.get("properties", {})
        for key, value in args.items():
            if key not in properties:
                raise ToolValidationError(f"{self.name} got unknown argument: {key}")
            expected = properties[key].get("type")
            if expected and not _matches_json_type(value, expected):
                raise ToolValidationError(
                    f"{self.name}.{key} expected {expected}, got {type(value).__name__}"
                )

    def dry_run(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if not self.dry_run_supported:
            return ToolResult.success("No dry-run behavior is defined for this tool.")
        return self.execute(args, ToolContext(**{**context.__dict__, "dry_run": True}))

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        raise NotImplementedError

    def expected_impact(self, args: dict[str, Any]) -> str:
        return f"Runs the {self.name} tool."

    def rollback_notes(self, args: dict[str, Any]) -> str:
        return "No automatic rollback is available."

    def tool_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }


def _matches_json_type(value: Any, expected: str | list[str]) -> bool:
    expected_types = [expected] if isinstance(expected, str) else expected
    mapping = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    if value is None:
        return "null" in expected_types
    for item in expected_types:
        py_type = mapping.get(item)
        if py_type is not None and isinstance(value, py_type):
            return True
    return False
