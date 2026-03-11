from src.agents.fundamental.subdomains.core_valuation.domain.models.dcf_growth.contracts import (
    DCFGrowthParams,
)
from src.agents.fundamental.subdomains.core_valuation.domain.valuation_model_registry import (
    ValuationModelRegistry,
)


def test_dcf_growth_skill_uses_dedicated_schema() -> None:
    skill = ValuationModelRegistry.get_model_runtime("dcf_growth")
    assert isinstance(skill, dict)
    assert skill["schema"] is DCFGrowthParams
