from __future__ import annotations

import re
from pathlib import Path

from dumbo.skills.schema import SkillDefinition, dump_skill, load_skill


class SkillLibrary:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def list_names(self) -> list[str]:
        return sorted(path.stem for path in self.directory.glob("*.yaml"))

    def load(self, name: str) -> SkillDefinition:
        return load_skill(self._path_for(name))

    def save(self, skill: SkillDefinition) -> Path:
        path = self._path_for(skill.name)
        dump_skill(path, skill)
        return path

    def delete(self, name: str) -> bool:
        path = self._path_for(name)
        if not path.exists():
            return False
        path.unlink()
        return True

    def _path_for(self, name: str) -> Path:
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip()).strip("._")
        if not slug:
            raise ValueError("Skill name cannot be empty")
        return self.directory / f"{slug}.yaml"
