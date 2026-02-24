from src.agents.fundamental.domain.valuation.registry import SkillRegistry
from src.agents.fundamental.domain.valuation.skills.valuation_dcf_growth.schemas import (
    DCFGrowthParams,
)


def test_dcf_growth_skill_uses_dedicated_schema() -> None:
    skill = SkillRegistry.get_skill("dcf_growth")
    assert isinstance(skill, dict)
    assert skill["schema"] is DCFGrowthParams
