from __future__ import annotations

from collections.abc import Mapping

from .dcf_variant_contracts import DcfMonteCarloPolicy
from .dcf_variant_sensitivity_contracts import (
    DcfSensitivityCase,
    DcfSensitivitySummary,
    ShockDimension,
)

_WACC_SHOCKS_BP: tuple[int, ...] = (-100, -50, 50, 100)
_TERMINAL_GROWTH_SHOCKS_BP: tuple[int, ...] = (-50, -25, 25, 50)
_GROWTH_LEVEL_SHOCKS_BP: tuple[int, ...] = (-200, -100, 100, 200)
_MARGIN_LEVEL_SHOCKS_BP: tuple[int, ...] = (-200, -100, 100, 200)
_TERMINAL_BUFFER = 0.005
_GROWTH_FLOOR = -0.95
_GROWTH_CEIL = 2.0
_MARGIN_FLOOR = -0.5
_MARGIN_CEIL = 0.95
_TOP_DRIVER_COUNT = 5


def run_dcf_variant_sensitivity(
    *,
    base_intrinsic_value: float,
    converged_inputs: Mapping[str, list[float]],
    static_inputs: Mapping[str, float],
    base_wacc: float,
    base_terminal_growth: float,
    policy: DcfMonteCarloPolicy,
) -> DcfSensitivitySummary:
    growth_rates = _require_series(converged_inputs, "growth_rates_converged")
    operating_margins = _require_series(converged_inputs, "operating_margins_converged")
    da_rates = _require_series(converged_inputs, "da_rates_converged")
    capex_rates = _require_series(converged_inputs, "capex_rates_converged")
    wc_rates = _require_series(converged_inputs, "wc_rates_converged")
    sbc_rates = _require_series(converged_inputs, "sbc_rates_converged")

    _assert_same_length(growth_rates, operating_margins, "operating_margins_converged")
    _assert_same_length(growth_rates, da_rates, "da_rates_converged")
    _assert_same_length(growth_rates, capex_rates, "capex_rates_converged")
    _assert_same_length(growth_rates, wc_rates, "wc_rates_converged")
    _assert_same_length(growth_rates, sbc_rates, "sbc_rates_converged")

    initial_revenue = _require_scalar(static_inputs, "initial_revenue")
    tax_rate = _require_scalar(static_inputs, "tax_rate")
    cash = _require_scalar(static_inputs, "cash")
    total_debt = _require_scalar(static_inputs, "total_debt")
    preferred_stock = _require_scalar(static_inputs, "preferred_stock")
    shares_outstanding = _require_scalar(static_inputs, "shares_outstanding")

    scenarios: list[DcfSensitivityCase] = []
    scenarios.extend(
        _build_wacc_scenarios(
            base_intrinsic_value=base_intrinsic_value,
            growth_rates=growth_rates,
            operating_margins=operating_margins,
            da_rates=da_rates,
            capex_rates=capex_rates,
            wc_rates=wc_rates,
            sbc_rates=sbc_rates,
            initial_revenue=initial_revenue,
            tax_rate=tax_rate,
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
            base_wacc=base_wacc,
            base_terminal_growth=base_terminal_growth,
            policy=policy,
        )
    )
    scenarios.extend(
        _build_terminal_growth_scenarios(
            base_intrinsic_value=base_intrinsic_value,
            growth_rates=growth_rates,
            operating_margins=operating_margins,
            da_rates=da_rates,
            capex_rates=capex_rates,
            wc_rates=wc_rates,
            sbc_rates=sbc_rates,
            initial_revenue=initial_revenue,
            tax_rate=tax_rate,
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
            base_wacc=base_wacc,
            base_terminal_growth=base_terminal_growth,
            policy=policy,
        )
    )
    scenarios.extend(
        _build_growth_level_scenarios(
            base_intrinsic_value=base_intrinsic_value,
            growth_rates=growth_rates,
            operating_margins=operating_margins,
            da_rates=da_rates,
            capex_rates=capex_rates,
            wc_rates=wc_rates,
            sbc_rates=sbc_rates,
            initial_revenue=initial_revenue,
            tax_rate=tax_rate,
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
            base_wacc=base_wacc,
            base_terminal_growth=base_terminal_growth,
            policy=policy,
        )
    )
    scenarios.extend(
        _build_margin_level_scenarios(
            base_intrinsic_value=base_intrinsic_value,
            growth_rates=growth_rates,
            operating_margins=operating_margins,
            da_rates=da_rates,
            capex_rates=capex_rates,
            wc_rates=wc_rates,
            sbc_rates=sbc_rates,
            initial_revenue=initial_revenue,
            tax_rate=tax_rate,
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
            base_wacc=base_wacc,
            base_terminal_growth=base_terminal_growth,
            policy=policy,
        )
    )

    max_upside = 0.0
    max_downside = 0.0
    for case in scenarios:
        delta = case["delta_pct_vs_base"]
        if delta > max_upside:
            max_upside = delta
        if delta < max_downside:
            max_downside = delta

    ranked = sorted(
        scenarios,
        key=lambda item: abs(item["delta_pct_vs_base"]),
        reverse=True,
    )
    top_drivers = ranked[:_TOP_DRIVER_COUNT]

    return {
        "base_intrinsic_value": float(base_intrinsic_value),
        "scenario_count": len(scenarios),
        "max_upside_delta_pct": max_upside,
        "max_downside_delta_pct": max_downside,
        "top_drivers": top_drivers,
        "cases": scenarios,
    }


def _build_wacc_scenarios(
    *,
    base_intrinsic_value: float,
    growth_rates: list[float],
    operating_margins: list[float],
    da_rates: list[float],
    capex_rates: list[float],
    wc_rates: list[float],
    sbc_rates: list[float],
    initial_revenue: float,
    tax_rate: float,
    cash: float,
    total_debt: float,
    preferred_stock: float,
    shares_outstanding: float,
    base_wacc: float,
    base_terminal_growth: float,
    policy: DcfMonteCarloPolicy,
) -> list[DcfSensitivityCase]:
    cases: list[DcfSensitivityCase] = []
    for shock_bp in _WACC_SHOCKS_BP:
        shocked_wacc = _clamp(
            base_wacc + _bp_to_rate(shock_bp),
            policy.wacc_min,
            policy.wacc_max,
        )
        terminal_growth, guard_applied = _guard_terminal_growth(
            wacc=shocked_wacc,
            terminal_growth=base_terminal_growth,
            policy=policy,
        )
        intrinsic_value = _evaluate_intrinsic_value(
            growth_rates=growth_rates,
            operating_margins=operating_margins,
            da_rates=da_rates,
            capex_rates=capex_rates,
            wc_rates=wc_rates,
            sbc_rates=sbc_rates,
            initial_revenue=initial_revenue,
            tax_rate=tax_rate,
            wacc=shocked_wacc,
            terminal_growth=terminal_growth,
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
        )
        cases.append(
            _build_case(
                base_intrinsic_value=base_intrinsic_value,
                shock_dimension="wacc",
                shock_value_bp=shock_bp,
                intrinsic_value=intrinsic_value,
                guard_applied=guard_applied,
            )
        )
    return cases


def _build_terminal_growth_scenarios(
    *,
    base_intrinsic_value: float,
    growth_rates: list[float],
    operating_margins: list[float],
    da_rates: list[float],
    capex_rates: list[float],
    wc_rates: list[float],
    sbc_rates: list[float],
    initial_revenue: float,
    tax_rate: float,
    cash: float,
    total_debt: float,
    preferred_stock: float,
    shares_outstanding: float,
    base_wacc: float,
    base_terminal_growth: float,
    policy: DcfMonteCarloPolicy,
) -> list[DcfSensitivityCase]:
    cases: list[DcfSensitivityCase] = []
    for shock_bp in _TERMINAL_GROWTH_SHOCKS_BP:
        shocked_terminal = _clamp(
            base_terminal_growth + _bp_to_rate(shock_bp),
            policy.terminal_min,
            policy.terminal_max,
        )
        terminal_growth, guard_applied = _guard_terminal_growth(
            wacc=base_wacc,
            terminal_growth=shocked_terminal,
            policy=policy,
        )
        intrinsic_value = _evaluate_intrinsic_value(
            growth_rates=growth_rates,
            operating_margins=operating_margins,
            da_rates=da_rates,
            capex_rates=capex_rates,
            wc_rates=wc_rates,
            sbc_rates=sbc_rates,
            initial_revenue=initial_revenue,
            tax_rate=tax_rate,
            wacc=base_wacc,
            terminal_growth=terminal_growth,
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
        )
        cases.append(
            _build_case(
                base_intrinsic_value=base_intrinsic_value,
                shock_dimension="terminal_growth",
                shock_value_bp=shock_bp,
                intrinsic_value=intrinsic_value,
                guard_applied=guard_applied,
            )
        )
    return cases


def _build_growth_level_scenarios(
    *,
    base_intrinsic_value: float,
    growth_rates: list[float],
    operating_margins: list[float],
    da_rates: list[float],
    capex_rates: list[float],
    wc_rates: list[float],
    sbc_rates: list[float],
    initial_revenue: float,
    tax_rate: float,
    cash: float,
    total_debt: float,
    preferred_stock: float,
    shares_outstanding: float,
    base_wacc: float,
    base_terminal_growth: float,
    policy: DcfMonteCarloPolicy,
) -> list[DcfSensitivityCase]:
    cases: list[DcfSensitivityCase] = []
    for shock_bp in _GROWTH_LEVEL_SHOCKS_BP:
        shock_rate = _bp_to_rate(shock_bp)
        shocked_growth = [
            _clamp(value + shock_rate, _GROWTH_FLOOR, _GROWTH_CEIL)
            for value in growth_rates
        ]
        terminal_growth, guard_applied = _guard_terminal_growth(
            wacc=base_wacc,
            terminal_growth=base_terminal_growth,
            policy=policy,
        )
        intrinsic_value = _evaluate_intrinsic_value(
            growth_rates=shocked_growth,
            operating_margins=operating_margins,
            da_rates=da_rates,
            capex_rates=capex_rates,
            wc_rates=wc_rates,
            sbc_rates=sbc_rates,
            initial_revenue=initial_revenue,
            tax_rate=tax_rate,
            wacc=base_wacc,
            terminal_growth=terminal_growth,
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
        )
        cases.append(
            _build_case(
                base_intrinsic_value=base_intrinsic_value,
                shock_dimension="growth_level",
                shock_value_bp=shock_bp,
                intrinsic_value=intrinsic_value,
                guard_applied=guard_applied,
            )
        )
    return cases


def _build_margin_level_scenarios(
    *,
    base_intrinsic_value: float,
    growth_rates: list[float],
    operating_margins: list[float],
    da_rates: list[float],
    capex_rates: list[float],
    wc_rates: list[float],
    sbc_rates: list[float],
    initial_revenue: float,
    tax_rate: float,
    cash: float,
    total_debt: float,
    preferred_stock: float,
    shares_outstanding: float,
    base_wacc: float,
    base_terminal_growth: float,
    policy: DcfMonteCarloPolicy,
) -> list[DcfSensitivityCase]:
    cases: list[DcfSensitivityCase] = []
    for shock_bp in _MARGIN_LEVEL_SHOCKS_BP:
        shock_rate = _bp_to_rate(shock_bp)
        shocked_margins = [
            _clamp(value + shock_rate, _MARGIN_FLOOR, _MARGIN_CEIL)
            for value in operating_margins
        ]
        terminal_growth, guard_applied = _guard_terminal_growth(
            wacc=base_wacc,
            terminal_growth=base_terminal_growth,
            policy=policy,
        )
        intrinsic_value = _evaluate_intrinsic_value(
            growth_rates=growth_rates,
            operating_margins=shocked_margins,
            da_rates=da_rates,
            capex_rates=capex_rates,
            wc_rates=wc_rates,
            sbc_rates=sbc_rates,
            initial_revenue=initial_revenue,
            tax_rate=tax_rate,
            wacc=base_wacc,
            terminal_growth=terminal_growth,
            cash=cash,
            total_debt=total_debt,
            preferred_stock=preferred_stock,
            shares_outstanding=shares_outstanding,
        )
        cases.append(
            _build_case(
                base_intrinsic_value=base_intrinsic_value,
                shock_dimension="margin_level",
                shock_value_bp=shock_bp,
                intrinsic_value=intrinsic_value,
                guard_applied=guard_applied,
            )
        )
    return cases


def _evaluate_intrinsic_value(
    *,
    growth_rates: list[float],
    operating_margins: list[float],
    da_rates: list[float],
    capex_rates: list[float],
    wc_rates: list[float],
    sbc_rates: list[float],
    initial_revenue: float,
    tax_rate: float,
    wacc: float,
    terminal_growth: float,
    cash: float,
    total_debt: float,
    preferred_stock: float,
    shares_outstanding: float,
) -> float:
    years = len(growth_rates)
    projected_revenue: list[float] = []
    revenue = float(initial_revenue)
    for growth_rate in growth_rates:
        revenue *= 1.0 + growth_rate
        projected_revenue.append(revenue)

    fcff: list[float] = []
    previous_revenue = float(initial_revenue)
    for index in range(years):
        current_revenue = projected_revenue[index]
        ebit = current_revenue * operating_margins[index]
        nopat = ebit * (1.0 - tax_rate)
        da = current_revenue * da_rates[index]
        capex = current_revenue * capex_rates[index]
        delta_wc = (current_revenue - previous_revenue) * wc_rates[index]
        fcff.append(nopat + da - capex - delta_wc)
        previous_revenue = current_revenue

    pv_fcff = 0.0
    for index, cash_flow in enumerate(fcff, start=1):
        pv_fcff += cash_flow / ((1.0 + wacc) ** index)

    final_fcff = fcff[-1]
    terminal_value = final_fcff * (1.0 + terminal_growth) / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1.0 + wacc) ** years)

    enterprise_value = pv_fcff + pv_terminal
    equity_value = enterprise_value + cash - total_debt - preferred_stock
    return equity_value / shares_outstanding


def _build_case(
    *,
    base_intrinsic_value: float,
    shock_dimension: ShockDimension,
    shock_value_bp: int,
    intrinsic_value: float,
    guard_applied: bool,
) -> DcfSensitivityCase:
    return {
        "scenario_id": f"{shock_dimension}_{shock_value_bp:+d}bp",
        "shock_dimension": shock_dimension,
        "shock_value_bp": shock_value_bp,
        "intrinsic_value": intrinsic_value,
        "delta_pct_vs_base": _pct_delta(
            base_value=base_intrinsic_value,
            shifted_value=intrinsic_value,
        ),
        "guard_applied": guard_applied,
    }


def _guard_terminal_growth(
    *,
    wacc: float,
    terminal_growth: float,
    policy: DcfMonteCarloPolicy,
) -> tuple[float, bool]:
    guarded = _clamp(terminal_growth, policy.terminal_min, policy.terminal_max)
    max_allowed = wacc - _TERMINAL_BUFFER
    if guarded <= max_allowed:
        return guarded, False
    adjusted = _clamp(max_allowed, policy.terminal_min, policy.terminal_max)
    return adjusted, True


def _pct_delta(*, base_value: float, shifted_value: float) -> float:
    denominator = abs(base_value) if abs(base_value) > 1e-9 else 1.0
    return (shifted_value - base_value) / denominator


def _bp_to_rate(shock_bp: int) -> float:
    return float(shock_bp) / 10_000.0


def _require_series(payload: Mapping[str, list[float]], key: str) -> list[float]:
    value = payload.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{key} must be non-empty list[float]")
    output: list[float] = []
    for item in value:
        output.append(float(item))
    return output


def _assert_same_length(reference: list[float], series: list[float], name: str) -> None:
    if len(reference) != len(series):
        raise ValueError(f"{name} length must equal growth_rates_converged length")


def _require_scalar(payload: Mapping[str, float], key: str) -> float:
    value = payload.get(key)
    if value is None:
        raise ValueError(f"{key} is required")
    return float(value)


def _clamp(value: float, lower: float, upper: float) -> float:
    if value < lower:
        return lower
    if value > upper:
        return upper
    return value
