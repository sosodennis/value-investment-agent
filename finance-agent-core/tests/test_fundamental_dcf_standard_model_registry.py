from src.agents.fundamental.domain.valuation.models.dcf_standard.contracts import (
    DCFStandardParams,
)
from src.agents.fundamental.domain.valuation.valuation_model_registry import (
    ValuationModelRegistry,
)


def test_dcf_standard_skill_uses_dedicated_schema() -> None:
    skill = ValuationModelRegistry.get_model_runtime("dcf_standard")
    assert isinstance(skill, dict)
    assert skill["schema"] is DCFStandardParams
