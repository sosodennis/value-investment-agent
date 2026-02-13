from __future__ import annotations

from ..core import CalculationGraph


def project_revenue(initial_revenue: float, growth_rates: list[float]) -> list[float]:
    revenue: list[float] = []
    current = initial_revenue
    for g in growth_rates:
        current = current * (1 + g)
        revenue.append(current)
    return revenue


def calculate_ebit(
    projected_revenue: list[float], operating_margins: list[float]
) -> list[float]:
    return [r * m for r, m in zip(projected_revenue, operating_margins, strict=False)]


def calculate_nopat(ebit: list[float], tax_rate: float) -> list[float]:
    return [e * (1 - tax_rate) for e in ebit]


def calculate_delta_wc(
    projected_revenue: list[float],
    initial_revenue: float,
    wc_rates: list[float],
) -> list[float]:
    deltas: list[float] = []
    prev = initial_revenue
    for r, wc in zip(projected_revenue, wc_rates, strict=False):
        delta_rev = r - prev
        deltas.append(delta_rev * wc)
        prev = r
    return deltas


def calculate_fcff(
    nopat: list[float],
    projected_revenue: list[float],
    da_rates: list[float],
    capex_rates: list[float],
    delta_wc: list[float],
    sbc_rates: list[float],
) -> list[float]:
    fcff: list[float] = []
    for i, r in enumerate(projected_revenue):
        da = r * da_rates[i]
        capex = r * capex_rates[i]
        sbc = r * sbc_rates[i]
        f = nopat[i] + da - capex - delta_wc[i] + sbc
        fcff.append(f)
    return fcff


def calculate_terminal_value(
    final_fcff: float, wacc: float, terminal_growth: float
) -> float:
    if terminal_growth >= wacc:
        raise ValueError("Terminal growth rate must be less than WACC")
    return (final_fcff * (1 + terminal_growth)) / (wacc - terminal_growth)


def calculate_pv_fcff(fcff: list[float], wacc: float) -> float:
    pv = 0.0
    for t, cash_flow in enumerate(fcff):
        pv += cash_flow / ((1 + wacc) ** (t + 1))
    return pv


def calculate_pv_terminal(
    terminal_value: float, wacc: float, projection_years: int
) -> float:
    return terminal_value / ((1 + wacc) ** projection_years)


def calculate_enterprise_value(pv_fcff: float, pv_terminal: float) -> float:
    return pv_fcff + pv_terminal


def calculate_equity_value(
    enterprise_value: float, cash: float, total_debt: float, preferred_stock: float
) -> float:
    return enterprise_value + cash - total_debt - preferred_stock


def calculate_intrinsic_value(equity_value: float, shares_outstanding: float) -> float:
    if shares_outstanding <= 0:
        raise ValueError("Shares outstanding must be positive")
    return equity_value / shares_outstanding


def create_saas_graph() -> CalculationGraph:
    graph = CalculationGraph("SaaS_FCFF")

    graph.add_node("projected_revenue", project_revenue)
    graph.add_node("ebit", calculate_ebit)
    graph.add_node("nopat", calculate_nopat)
    graph.add_node("delta_wc", calculate_delta_wc)
    graph.add_node("fcff", calculate_fcff)

    def get_final_fcff(fcff: list[float]) -> float:
        return fcff[-1]

    def projection_years(fcff: list[float]) -> int:
        return len(fcff)

    graph.add_node("final_fcff", get_final_fcff)
    graph.add_node("terminal_value", calculate_terminal_value)
    graph.add_node("pv_fcff", calculate_pv_fcff)
    graph.add_node("projection_years", projection_years)
    graph.add_node("pv_terminal", calculate_pv_terminal)
    graph.add_node("enterprise_value", calculate_enterprise_value)
    graph.add_node("equity_value", calculate_equity_value)
    graph.add_node("intrinsic_value", calculate_intrinsic_value)

    return graph
