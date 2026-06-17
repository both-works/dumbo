from __future__ import annotations

from dumbo.agent.ollama_client import OllamaClient
from dumbo.config import DumboConfig, ModelProfile
from dumbo.memory.sqlite_store import SQLiteMemoryStore
from dumbo.paths import AppPaths
from dumbo.skills.library import SkillLibrary
from dumbo.tools.apps import apps_tools
from dumbo.tools.browser import browser_tools
from dumbo.tools.desktop import desktop_tools
from dumbo.tools.filesystem import filesystem_tools
from dumbo.tools.media import media_tools
from dumbo.tools.memory import memory_tools
from dumbo.tools.powershell import powershell_tools
from dumbo.tools.registry import ToolRegistry
from dumbo.tools.skills import skills_tools
from dumbo.tools.vision import vision_tools


def build_default_registry(
    *,
    config: DumboConfig,
    profile: ModelProfile,
    paths: AppPaths,
    memory_store: SQLiteMemoryStore,
    skill_library: SkillLibrary,
    ollama: OllamaClient,
) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in [
        *filesystem_tools(config),
        *apps_tools(config),
        *powershell_tools(config),
        *browser_tools(config),
        *desktop_tools(paths),
        *vision_tools(ollama, profile, config, paths),
        *media_tools(),
        *memory_tools(memory_store),
    ]:
        registry.register(tool)
    for tool in skills_tools(skill_library, registry):
        registry.register(tool)
    return registry
