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


def converge_growth_rates_standard(
    growth_rates: list[float], terminal_growth: float
) -> list[float]:
    if not growth_rates:
        raise ValueError("growth_rates cannot be empty")
    target = clamp(terminal_growth, -0.01, 0.04)
    start = max(1, len(growth_rates) // 2)
    return converge_series(
        growth_rates,
        target=target,
        start_index=start,
        min_value=-0.40,
        max_value=0.80,
    )


def converge_operating_margins_standard(
    operating_margins: list[float],
) -> list[float]:
    if not operating_margins:
        raise ValueError("operating_margins cannot be empty")
    target = clamp(operating_margins[-1], 0.08, 0.30)
    start = max(1, len(operating_margins) // 2)
    return converge_series(
        operating_margins,
        target=target,
        start_index=start,
        min_value=-0.20,
        max_value=0.45,
    )


def converge_da_rates_standard(da_rates: list[float]) -> list[float]:
    if not da_rates:
        raise ValueError("da_rates cannot be empty")
    target = clamp(da_rates[-1], 0.015, 0.08)
    start = max(1, len(da_rates) // 2)
    return converge_series(
        da_rates,
        target=target,
        start_index=start,
        min_value=0.0,
        max_value=0.12,
    )


def converge_capex_rates_standard(
    capex_rates: list[float], da_rates_converged: list[float]
) -> list[float]:
    if not capex_rates:
        raise ValueError("capex_rates cannot be empty")
    da_anchor = clamp(da_rates_converged[-1], 0.015, 0.08)
    target = max(da_anchor * 1.05, clamp(capex_rates[-1], 0.03, 0.12))
    start = max(1, len(capex_rates) // 2)
    return converge_series(
        capex_rates,
        target=target,
        start_index=start,
        min_value=0.0,
        max_value=0.18,
    )


def converge_wc_rates_standard(wc_rates: list[float]) -> list[float]:
    if not wc_rates:
        raise ValueError("wc_rates cannot be empty")
    target = clamp(wc_rates[-1], 0.0, 0.08)
    start = max(1, len(wc_rates) // 2)
    return converge_series(
        wc_rates,
        target=target,
        start_index=start,
        min_value=-0.05,
        max_value=0.15,
    )


def converge_sbc_rates_standard(sbc_rates: list[float]) -> list[float]:
    if not sbc_rates:
        raise ValueError("sbc_rates cannot be empty")
    target = clamp(min(sbc_rates[-1], 0.03), 0.0, 0.08)
    start = max(1, len(sbc_rates) // 2)
    return converge_series(
        sbc_rates,
        target=target,
        start_index=start,
        min_value=0.0,
        max_value=0.12,
    )


def create_dcf_standard_graph() -> CalculationGraph:
    graph = CalculationGraph("DCF_STANDARD")

    graph.add_node("projection_years", projection_years)
    graph.add_node("growth_rates_converged", converge_growth_rates_standard)
    graph.add_node("operating_margins_converged", converge_operating_margins_standard)
    graph.add_node("da_rates_converged", converge_da_rates_standard)
    graph.add_node("capex_rates_converged", converge_capex_rates_standard)
    graph.add_node("wc_rates_converged", converge_wc_rates_standard)
    graph.add_node("sbc_rates_converged", converge_sbc_rates_standard)

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
