from __future__ import annotations

from typing import Any

from dumbo.skills.library import SkillLibrary
from dumbo.skills.schema import SkillDefinition, validate_skill_against_registry
from dumbo.tools.base import BaseTool, RiskLevel, ToolContext, ToolResult, ToolValidationError
from dumbo.tools.registry import ToolRegistry


class DefineSkillTool(BaseTool):
    name = "define_skill"
    description = "Save a reusable YAML skill made of named tool steps."
    risk_level = RiskLevel.WRITE_SAFE
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "intent_examples": {"type": "array"},
            "steps": {"type": "array"},
            "risk_level": {"type": "string"},
        },
        "required": ["name", "description", "intent_examples", "steps", "risk_level"],
    }

    def __init__(self, library: SkillLibrary, registry: ToolRegistry):
        self.library = library
        self.registry = registry

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        try:
            skill = SkillDefinition.from_dict(args)
            validate_skill_against_registry(skill, self.registry)
        except Exception as exc:
            raise ToolValidationError(str(exc)) from exc
        if context.dry_run:
            return ToolResult.success(f"Would define skill {skill.name}.")
        path = self.library.save(skill)
        return ToolResult.success(f"Defined skill {skill.name}.", {"path": str(path)})


class ListSkillsTool(BaseTool):
    name = "list_skills"
    description = "List locally defined skills."
    risk_level = RiskLevel.READ_ONLY
    parameters_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self, library: SkillLibrary):
        self.library = library

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        names = self.library.list_names()
        return ToolResult.success(f"Listed {len(names)} skills.", {"skills": names})


class DeleteSkillTool(BaseTool):
    name = "delete_skill"
    description = "Delete a locally defined skill by name."
    risk_level = RiskLevel.DESTRUCTIVE
    parameters_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    }

    def __init__(self, library: SkillLibrary):
        self.library = library

    def execute(self, args: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.dry_run:
            return ToolResult.success(f"Would delete skill {args['name']}.")
        deleted = self.library.delete(args["name"])
        return ToolResult.success("Deleted skill." if deleted else "No matching skill existed.")


def skills_tools(library: SkillLibrary, registry: ToolRegistry) -> list[BaseTool]:
    return [DefineSkillTool(library, registry), ListSkillsTool(library), DeleteSkillTool(library)]
