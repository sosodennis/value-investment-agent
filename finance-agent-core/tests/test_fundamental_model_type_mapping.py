from src.agents.fundamental.domain.valuation_model_type_service import (
    resolve_calculator_model_type,
)


def test_resolve_calculator_model_type_uses_explicit_dcf_standard() -> None:
    assert resolve_calculator_model_type("dcf_standard") == "dcf_standard"


def test_resolve_calculator_model_type_uses_explicit_dcf_growth() -> None:
    assert resolve_calculator_model_type("dcf_growth") == "dcf_growth"
