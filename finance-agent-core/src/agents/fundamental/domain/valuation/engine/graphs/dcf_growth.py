from __future__ import annotations

from ..core import CalculationGraph
from .dcf_common import (
    calculate_delta_wc,
    calculate_ebit,
    calculate_enterprise_value,
    calculate_equity_value,
    calculate_fcff,
    calculate_intrinsic_value,
    calculate_nopat,
    calculate_pv_fcff,
    calculate_pv_terminal,
    calculate_reinvestment_rates,
    calculate_terminal_value,
    clamp,
    converge_series,
    effective_terminal_growth,
    final_fcff,
    project_revenue,
    projection_years,
)

HIGH_MARGIN_REGIME_TRIGGER = 0.50
BASE_MARGIN_TARGET_CEILING = 0.42
BASE_MARGIN_SERIES_CEILING = 0.55
HIGH_MARGIN_TARGET_CEILING = 0.60
HIGH_MARGIN_SERIES_CEILING = 0.70
SHORT_HORIZON_YEARS = 5
SHORT_HORIZON_TERMINAL_BRIDGE_SPREAD = 0.01


def _growth_convergence_start(length: int) -> int:
    if length <= 2:
        return 1
    return max(2, int(length * 0.65))


def _late_growth_rate_convergence_start(length: int) -> int:
    if length <= 3:
        return 1
    # For short horizons, avoid over-compressing early growth.
    # Keep at least the first 4 years before fading to terminal.
    return max(3, length - 4)


def converge_growth_rates_growth(
    growth_rates: list[float], terminal_growth: float
) -> list[float]:
    if not growth_rates:
        raise ValueError("growth_rates cannot be empty")
    target = clamp(terminal_growth, -0.005, 0.05)
    raw_last = clamp(growth_rates[-1], -0.50, 1.20)
    if len(growth_rates) <= SHORT_HORIZON_YEARS and raw_last > target:
        bridge_target = min(raw_last, target + SHORT_HORIZON_TERMINAL_BRIDGE_SPREAD)
        target = max(target, bridge_target)
    return converge_series(
        growth_rates,
        target=target,
        start_index=_late_growth_rate_convergence_start(len(growth_rates)),
        min_value=-0.50,
        max_value=1.20,
    )


def converge_operating_margins_growth(
    operating_margins: list[float],
) -> list[float]:
    if not operating_margins:
        raise ValueError("operating_margins cannot be empty")
    trailing_margin = float(operating_margins[-1])
    target_ceiling = BASE_MARGIN_TARGET_CEILING
    series_ceiling = BASE_MARGIN_SERIES_CEILING
    if trailing_margin >= HIGH_MARGIN_REGIME_TRIGGER:
        target_ceiling = HIGH_MARGIN_TARGET_CEILING
        series_ceiling = HIGH_MARGIN_SERIES_CEILING
    target = clamp(max(trailing_margin, 0.18), 0.10, target_ceiling)
    return converge_series(
        operating_margins,
        target=target,
        start_index=_growth_convergence_start(len(operating_margins)),
        min_value=-0.25,
        max_value=series_ceiling,
    )


def converge_da_rates_growth(da_rates: list[float]) -> list[float]:
    if not da_rates:
        raise ValueError("da_rates cannot be empty")
    target = clamp(da_rates[-1], 0.02, 0.10)
    return converge_series(
        da_rates,
        target=target,
        start_index=_growth_convergence_start(len(da_rates)),
        min_value=0.0,
        max_value=0.15,
    )


def converge_capex_rates_growth(
    capex_rates: list[float], da_rates_converged: list[float]
) -> list[float]:
    if not capex_rates:
        raise ValueError("capex_rates cannot be empty")
    da_anchor = clamp(da_rates_converged[-1], 0.02, 0.10)
    target = max(da_anchor * 1.20, clamp(capex_rates[-1], 0.04, 0.18))
    return converge_series(
        capex_rates,
        target=target,
        start_index=_growth_convergence_start(len(capex_rates)),
        min_value=0.0,
        max_value=0.25,
    )


def converge_wc_rates_growth(wc_rates: list[float]) -> list[float]:
    if not wc_rates:
        raise ValueError("wc_rates cannot be empty")
    target = clamp(wc_rates[-1], 0.0, 0.12)
    return converge_series(
        wc_rates,
        target=target,
        start_index=_growth_convergence_start(len(wc_rates)),
        min_value=-0.08,
        max_value=0.20,
    )


def converge_sbc_rates_growth(sbc_rates: list[float]) -> list[float]:
    if not sbc_rates:
        raise ValueError("sbc_rates cannot be empty")
    target = clamp(min(sbc_rates[-1], 0.05), 0.0, 0.12)
    return converge_series(
        sbc_rates,
        target=target,
        start_index=_growth_convergence_start(len(sbc_rates)),
        min_value=0.0,
        max_value=0.18,
    )


def create_dcf_growth_graph() -> CalculationGraph:
    graph = CalculationGraph("DCF_GROWTH")

    graph.add_node("projection_years", projection_years)
    graph.add_node("growth_rates_converged", converge_growth_rates_growth)
    graph.add_node("operating_margins_converged", converge_operating_margins_growth)
    graph.add_node("da_rates_converged", converge_da_rates_growth)
    graph.add_node("capex_rates_converged", converge_capex_rates_growth)
    graph.add_node("wc_rates_converged", converge_wc_rates_growth)
    graph.add_node("sbc_rates_converged", converge_sbc_rates_growth)

    graph.add_node("projected_revenue", project_revenue)
    graph.add_node("ebit", calculate_ebit)
    graph.add_node("nopat", calculate_nopat)
    graph.add_node("delta_wc", calculate_delta_wc)
    graph.add_node("fcff", calculate_fcff)
    graph.add_node("reinvestment_rates", calculate_reinvestment_rates)

    graph.add_node("final_fcff", final_fcff)
    graph.add_node("terminal_growth_effective", effective_terminal_growth)
    graph.add_node("terminal_value", calculate_terminal_value)
    graph.add_node("pv_fcff", calculate_pv_fcff)
    graph.add_node("pv_terminal", calculate_pv_terminal)
    graph.add_node("enterprise_value", calculate_enterprise_value)
    graph.add_node("equity_value", calculate_equity_value)
    graph.add_node("intrinsic_value", calculate_intrinsic_value)

    return graph
