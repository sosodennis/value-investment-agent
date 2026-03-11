from __future__ import annotations

import pytest

import src.agents.fundamental.core_valuation.domain.calculators.saas_calculator as saas_tools
from src.agents.fundamental.core_valuation.domain.calculators.dcf_growth_calculator import (
    calculate_dcf_growth_valuation,
)
from src.agents.fundamental.core_valuation.domain.calculators.dcf_standard_calculator import (
    calculate_dcf_standard_valuation,
)
from src.agents.fundamental.core_valuation.domain.models.dcf_growth.contracts import (
    DCFGrowthParams,
)
from src.agents.fundamental.core_valuation.domain.models.dcf_standard.contracts import (
    DCFStandardParams,
)


def _base_kwargs() -> dict[str, object]:
    return {
        "ticker": "DCF",
        "rationale": "unit-test",
        "initial_revenue": 220.0,
        "growth_rates": [0.22, 0.20, 0.18, 0.16, 0.14, 0.12, 0.10, 0.08, 0.07, 0.06],
        "operating_margins": [
            0.12,
            0.13,
            0.14,
            0.15,
            0.16,
            0.17,
            0.18,
            0.19,
            0.20,
            0.20,
        ],
        "tax_rate": 0.21,
        "da_rates": [0.03] * 10,
        "capex_rates": [
            0.06,
            0.06,
            0.058,
            0.056,
            0.054,
            0.052,
            0.050,
            0.050,
            0.050,
            0.050,
        ],
        "wc_rates": [
            0.012,
            0.011,
            0.011,
            0.010,
            0.010,
            0.010,
            0.009,
            0.009,
            0.009,
            0.009,
        ],
        "sbc_rates": [
            0.018,
            0.017,
            0.016,
            0.016,
            0.015,
            0.015,
            0.014,
            0.014,
            0.014,
            0.014,
        ],
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
    kwargs = _base_kwargs()
    kwargs["growth_rates"] = [0.15] * 10
    kwargs["terminal_growth"] = 0.03
    params = DCFStandardParams(**kwargs)
    result = calculate_dcf_standard_valuation(params)

    assert "error" not in result
    details = result["details"]
    assert isinstance(details, dict)

    growth = details.get("growth_rates_converged")
    terminal_effective = details.get("terminal_growth_effective")
    reinvestment = details.get("reinvestment_rates")
    sensitivity_summary = details.get("sensitivity_summary")
    sensitivity_cases = details.get("sensitivity_cases")

    assert isinstance(growth, list)
    assert isinstance(reinvestment, list)
    assert len(growth) == 10
    assert len(reinvestment) == 10
    assert isinstance(terminal_effective, float)
    assert growth[-1] == pytest.approx(terminal_effective, abs=1e-9)
    assert growth[:7] == pytest.approx([0.15] * 7)
    assert growth[7] < 0.15
    assert growth[7] > growth[8] > growth[9]
    assert isinstance(sensitivity_summary, dict)
    assert sensitivity_summary.get("enabled") is True
    assert sensitivity_summary.get("scenario_count") == 16
    assert isinstance(sensitivity_cases, list)
    assert len(sensitivity_cases) == 16


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


def test_dcf_growth_short_horizon_preserves_first_three_years_before_fade() -> None:
    kwargs = _base_kwargs()
    kwargs["growth_rates"] = [0.18, 0.16, 0.14, 0.12, 0.10]
    kwargs["operating_margins"] = [0.22, 0.24, 0.26, 0.28, 0.30]
    kwargs["da_rates"] = [0.03] * 5
    kwargs["capex_rates"] = [0.05] * 5
    kwargs["wc_rates"] = [0.01] * 5
    kwargs["sbc_rates"] = [0.02] * 5
    params = DCFGrowthParams(**kwargs)
    result = calculate_dcf_growth_valuation(params)

    assert "error" not in result
    details = result["details"]
    assert isinstance(details, dict)
    growth = details.get("growth_rates_converged")
    terminal_effective = details.get("terminal_growth_effective")
    assert isinstance(growth, list)
    assert isinstance(terminal_effective, float)
    assert len(growth) == 5
    assert growth[:3] == pytest.approx([0.18, 0.16, 0.14])
    assert growth[2] > growth[3] > growth[4]
    assert growth[4] >= terminal_effective
    assert growth[4] <= terminal_effective + 0.01 + 1e-9


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


def test_dcf_growth_preserves_high_margin_regime() -> None:
    kwargs = _base_kwargs()
    kwargs["operating_margins"] = [0.58] * 10
    params = DCFGrowthParams(**kwargs)
    result = calculate_dcf_growth_valuation(params)

    assert "error" not in result
    details = result["details"]
    assert isinstance(details, dict)
    margins = details.get("operating_margins_converged")
    assert isinstance(margins, list)
    assert margins == pytest.approx([0.58] * 10)


def test_dcf_standard_preserves_high_margin_regime_without_forcing_to_30pct() -> None:
    kwargs = _base_kwargs()
    kwargs["operating_margins"] = [0.36] * 10
    params = DCFStandardParams(**kwargs)
    result = calculate_dcf_standard_valuation(params)

    assert "error" not in result
    details = result["details"]
    assert isinstance(details, dict)
    margins = details.get("operating_margins_converged")
    assert isinstance(margins, list)
    assert margins == pytest.approx([0.36] * 10)


def test_dcf_standard_still_bounds_extreme_margin_regime() -> None:
    kwargs = _base_kwargs()
    kwargs["operating_margins"] = [0.58] * 10
    params = DCFStandardParams(**kwargs)
    result = calculate_dcf_standard_valuation(params)

    assert "error" not in result
    details = result["details"]
    assert isinstance(details, dict)
    margins = details.get("operating_margins_converged")
    assert isinstance(margins, list)
    assert margins[-1] == pytest.approx(0.40)


def test_dcf_standard_fcff_policy_ignores_sbc_addback() -> None:
    low_sbc_kwargs = _base_kwargs()
    low_sbc_kwargs["sbc_rates"] = [0.0] * 10
    low_sbc_result = calculate_dcf_standard_valuation(
        DCFStandardParams(**low_sbc_kwargs)
    )

    high_sbc_kwargs = _base_kwargs()
    high_sbc_kwargs["sbc_rates"] = [0.20] * 10
    high_sbc_result = calculate_dcf_standard_valuation(
        DCFStandardParams(**high_sbc_kwargs)
    )

    assert "error" not in low_sbc_result
    assert "error" not in high_sbc_result
    low_intrinsic = low_sbc_result.get("intrinsic_value")
    high_intrinsic = high_sbc_result.get("intrinsic_value")
    assert isinstance(low_intrinsic, float)
    assert isinstance(high_intrinsic, float)
    assert high_intrinsic == pytest.approx(low_intrinsic, rel=1e-9, abs=1e-9)
