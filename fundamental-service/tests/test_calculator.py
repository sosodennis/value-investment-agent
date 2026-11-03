import pytest

from fundamental_service.calculator import CalculationRefusal, calculate
from fundamental_service.testsupport import make_valuation


def test_calculator_is_deterministic_and_has_formula_nodes():
    request = make_valuation().with_digest()
    first = calculate(request, correlation_id="corr")
    second = calculate(request, correlation_id="corr")
    assert first.intrinsic_value == second.intrinsic_value
    assert first.result_hash == second.result_hash
    assert {node.node_id for node in first.nodes} >= {
        "wacc",
        "terminal_value",
        "per_share_value",
    }


def test_unverified_quality_refuses_calculation():
    request = (
        make_valuation()
        .model_copy(update={"quality": {"status": "provisional"}})
        .with_digest()
    )
    with pytest.raises(CalculationRefusal, match="verified"):
        calculate(request)


def test_missing_base_revenue_and_forged_digest_refuse():
    request = make_valuation().with_digest()
    missing = request.model_copy(
        update={
            "assumptions": request.assumptions.model_copy(
                update={
                    "forecast": request.assumptions.forecast.model_copy(
                        update={"base_revenue": None}
                    )
                }
            )
        }
    ).with_digest()
    with pytest.raises(CalculationRefusal, match="base revenue"):
        calculate(missing)
    forged = request.model_copy(update={"input_digest": "0" * 64})
    with pytest.raises(CalculationRefusal, match="input_digest"):
        calculate(forged)
