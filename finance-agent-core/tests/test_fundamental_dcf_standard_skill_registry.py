from src.agents.fundamental.domain.valuation.registry import SkillRegistry
from src.agents.fundamental.domain.valuation.skills.valuation_dcf_standard.schemas import (
    DCFStandardParams,
)


def test_dcf_standard_skill_uses_dedicated_schema() -> None:
    skill = SkillRegistry.get_skill("dcf_standard")
    assert isinstance(skill, dict)
    assert skill["schema"] is DCFStandardParams
