from __future__ import annotations

import pytest

from src.agents.fundamental.domain.valuation.calculators.dcf_standard_calculator import (
    calculate_dcf_standard_valuation,
)
from src.agents.fundamental.domain.valuation.calculators.dcf_variant_contracts import (
    DcfMonteCarloPolicy,
)
from src.agents.fundamental.domain.valuation.calculators.dcf_variant_result_service import (
    build_dcf_variant_static_inputs,
)
from src.agents.fundamental.domain.valuation.calculators.dcf_variant_sensitivity_service import (
    run_dcf_variant_sensitivity,
)
from src.agents.fundamental.domain.valuation.models.dcf_standard.contracts import (
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


def _policy() -> DcfMonteCarloPolicy:
    return DcfMonteCarloPolicy(
        growth_std_scale=0.8,
        growth_std_min=0.005,
        growth_clip_min=-0.25,
        growth_clip_max=0.25,
        margin_std_scale=0.8,
        margin_std_min=0.005,
        margin_clip_min=-0.12,
        margin_clip_max=0.12,
        wacc_min=0.03,
        wacc_max=0.30,
        terminal_min=-0.01,
        terminal_max=0.05,
    )


def _build_sensitivity_inputs() -> (
    tuple[float, dict[str, list[float]], dict[str, float]]
):
    params = DCFStandardParams(**_base_kwargs())
    result = calculate_dcf_standard_valuation(params)
    assert "error" not in result

    intrinsic_value_raw = result.get("intrinsic_value")
    assert isinstance(intrinsic_value_raw, float)

    details = result.get("details")
    assert isinstance(details, dict)
    converged_inputs = {
        "growth_rates_converged": _require_series(details, "growth_rates_converged"),
        "operating_margins_converged": _require_series(
            details, "operating_margins_converged"
        ),
        "da_rates_converged": _require_series(details, "da_rates_converged"),
        "capex_rates_converged": _require_series(details, "capex_rates_converged"),
        "wc_rates_converged": _require_series(details, "wc_rates_converged"),
        "sbc_rates_converged": _require_series(details, "sbc_rates_converged"),
    }
    static_inputs = build_dcf_variant_static_inputs(params)
    return intrinsic_value_raw, converged_inputs, static_inputs


def _require_series(payload: dict[str, object], key: str) -> list[float]:
    raw = payload.get(key)
    if not isinstance(raw, list):
        raise AssertionError(f"{key} is required in valuation details")
    return [float(item) for item in raw]


def test_run_dcf_variant_sensitivity_builds_expected_case_set() -> None:
    base_intrinsic_value, converged_inputs, static_inputs = _build_sensitivity_inputs()
    kwargs = _base_kwargs()
    summary = run_dcf_variant_sensitivity(
        base_intrinsic_value=base_intrinsic_value,
        converged_inputs=converged_inputs,
        static_inputs=static_inputs,
        base_wacc=float(kwargs["wacc"]),
        base_terminal_growth=float(kwargs["terminal_growth"]),
        policy=_policy(),
    )

    assert summary["scenario_count"] == 16
    assert len(summary["cases"]) == 16
    assert len(summary["top_drivers"]) == 5
    assert summary["max_upside_delta_pct"] > 0
    assert summary["max_downside_delta_pct"] < 0

    case_dimensions = {item["shock_dimension"] for item in summary["cases"]}
    assert case_dimensions == {
        "wacc",
        "terminal_growth",
        "growth_level",
        "margin_level",
    }

    wacc_up = next(
        item
        for item in summary["cases"]
        if item["shock_dimension"] == "wacc" and item["shock_value_bp"] == 100
    )
    wacc_down = next(
        item
        for item in summary["cases"]
        if item["shock_dimension"] == "wacc" and item["shock_value_bp"] == -100
    )
    assert wacc_down["intrinsic_value"] > wacc_up["intrinsic_value"]
    assert wacc_down["delta_pct_vs_base"] > 0
    assert wacc_up["delta_pct_vs_base"] < 0


def test_run_dcf_variant_sensitivity_marks_terminal_guard_when_needed() -> None:
    base_intrinsic_value, converged_inputs, static_inputs = _build_sensitivity_inputs()
    summary = run_dcf_variant_sensitivity(
        base_intrinsic_value=base_intrinsic_value,
        converged_inputs=converged_inputs,
        static_inputs=static_inputs,
        base_wacc=0.052,
        base_terminal_growth=0.054,
        policy=_policy(),
    )

    guarded_cases = [item for item in summary["cases"] if item["guard_applied"]]
    assert guarded_cases
    assert any(item["shock_dimension"] == "terminal_growth" for item in guarded_cases)


def test_run_dcf_variant_sensitivity_validates_required_series() -> None:
    base_intrinsic_value, converged_inputs, static_inputs = _build_sensitivity_inputs()
    invalid_inputs = dict(converged_inputs)
    invalid_inputs.pop("sbc_rates_converged")

    with pytest.raises(ValueError, match="sbc_rates_converged must be non-empty"):
        run_dcf_variant_sensitivity(
            base_intrinsic_value=base_intrinsic_value,
            converged_inputs=invalid_inputs,
            static_inputs=static_inputs,
            base_wacc=0.105,
            base_terminal_growth=0.028,
            policy=_policy(),
        )
