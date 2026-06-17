from pathlib import Path

from dumbo.skills.library import SkillLibrary
from dumbo.skills.schema import SkillDefinition, SkillStep
from dumbo.tools.base import RiskLevel


def test_skill_round_trip(tmp_path: Path) -> None:
    library = SkillLibrary(tmp_path)
    skill = SkillDefinition(
        name="open dashboard",
        description="Open a local dashboard",
        intent_examples=("open my dashboard",),
        steps=(SkillStep(tool="open_url", args={"url": "https://example.com"}),),
        risk_level=RiskLevel.LOW_RISK_OPEN,
    )
    path = library.save(skill)
    assert path.exists()
    assert library.list_names() == ["open_dashboard"]
    loaded = library.load("open dashboard")
    assert loaded.name == skill.name
    assert loaded.steps[0].tool == "open_url"
