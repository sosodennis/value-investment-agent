from src.agents.fundamental.domain.valuation.models.dcf_growth.contracts import (
    DCFGrowthParams,
)
from src.agents.fundamental.domain.valuation.valuation_model_registry import (
    ValuationModelRegistry,
)


def test_dcf_growth_skill_uses_dedicated_schema() -> None:
    skill = ValuationModelRegistry.get_model_runtime("dcf_growth")
    assert isinstance(skill, dict)
    assert skill["schema"] is DCFGrowthParams
