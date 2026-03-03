from __future__ import annotations

import pytest

import src.agents.fundamental.domain.valuation.calculators.saas_calculator as saas_tools
from src.agents.fundamental.domain.valuation.calculators.dcf_growth_calculator import (
    calculate_dcf_growth_valuation,
)
from src.agents.fundamental.domain.valuation.calculators.dcf_standard_calculator import (
    calculate_dcf_standard_valuation,
)
from src.agents.fundamental.domain.valuation.models.dcf_growth.contracts import (
    DCFGrowthParams,
)
from src.agents.fundamental.domain.valuation.models.dcf_standard.contracts import (
    DCFStandardParams,
)


def _base_kwargs() -> dict[str, object]:
    return {
        "ticker": "DCF",
        "rationale": "unit-test",
        "initial_revenue": 220.0,
        "growth_rates": [0.22, 0.18, 0.14, 0.10, 0.07],
        "operating_margins": [0.12, 0.14, 0.16, 0.18, 0.20],
        "tax_rate": 0.21,
        "da_rates": [0.03, 0.03, 0.03, 0.03, 0.03],
        "capex_rates": [0.06, 0.06, 0.055, 0.05, 0.05],
        "wc_rates": [0.012, 0.011, 0.010, 0.010, 0.009],
        "sbc_rates": [0.018, 0.017, 0.016, 0.015, 0.014],
        "wacc": 0.105,
        "terminal_growth": 0.028,
        "shares_outstanding": 120.0,
        "cash": 25.0,
        "total_debt": 12.0,
        "preferred_stock": 0.0,
        "current_price": 30.0,
    }


def test_dcf_standard_does_not_call_saas_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        saas_tools,
        "calculate_saas_valuation",
        lambda *_args, **_kwargs: {"error": "should_not_be_called"},
    )
    params = DCFStandardParams(**_base_kwargs())
    result = calculate_dcf_standard_valuation(params)

    assert "error" not in result
    assert "details" in result


def test_dcf_growth_does_not_call_saas_wrapper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        saas_tools,
        "calculate_saas_valuation",
        lambda *_args, **_kwargs: {"error": "should_not_be_called"},
    )
    params = DCFGrowthParams(**_base_kwargs())
    result = calculate_dcf_growth_valuation(params)

    assert "error" not in result
    assert "details" in result


def test_dcf_standard_outputs_converged_series_and_terminal_guard() -> None:
    params = DCFStandardParams(**_base_kwargs())
    result = calculate_dcf_standard_valuation(params)

    assert "error" not in result
    details = result["details"]
    assert isinstance(details, dict)

    growth = details.get("growth_rates_converged")
    terminal_effective = details.get("terminal_growth_effective")
    reinvestment = details.get("reinvestment_rates")

    assert isinstance(growth, list)
    assert isinstance(reinvestment, list)
    assert len(growth) == 5
    assert len(reinvestment) == 5
    assert isinstance(terminal_effective, float)
    assert growth[-1] == pytest.approx(terminal_effective, abs=1e-9)


def test_dcf_growth_includes_monte_carlo_distribution() -> None:
    params = DCFGrowthParams(
        **_base_kwargs(),
        monte_carlo_iterations=128,
        monte_carlo_seed=11,
        monte_carlo_sampler="pseudo",
    )
    result = calculate_dcf_growth_valuation(params)

    assert "error" not in result
    details = result["details"]
    assert isinstance(details, dict)
    distribution = details.get("distribution_summary")
    assert isinstance(distribution, dict)
    summary = distribution.get("summary")
    diagnostics = distribution.get("diagnostics")
    assert isinstance(summary, dict)
    assert isinstance(diagnostics, dict)
    assert diagnostics.get("sampler_type") == "pseudo"
    assert diagnostics.get("batch_evaluator_used") is True


def test_dcf_growth_monte_carlo_base_case_matches_point_intrinsic() -> None:
    params = DCFGrowthParams(
        **_base_kwargs(),
        monte_carlo_iterations=128,
        monte_carlo_seed=23,
        monte_carlo_sampler="pseudo",
    )
    result = calculate_dcf_growth_valuation(params)

    assert "error" not in result
    point_intrinsic = result.get("intrinsic_value")
    assert isinstance(point_intrinsic, float)

    details = result["details"]
    assert isinstance(details, dict)
    distribution = details.get("distribution_summary")
    assert isinstance(distribution, dict)
    diagnostics = distribution.get("diagnostics")
    assert isinstance(diagnostics, dict)
    base_case_intrinsic = diagnostics.get("base_case_intrinsic_value")
    assert isinstance(base_case_intrinsic, float)
    assert point_intrinsic == pytest.approx(base_case_intrinsic, rel=1e-9, abs=1e-9)
