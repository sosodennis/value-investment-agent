from __future__ import annotations

from ..core import CalculationGraph


def calculate_pv_projected_eva(projected_evas: list[float], wacc: float) -> float:
    pv = 0.0
    for t, eva in enumerate(projected_evas):
        pv += eva / ((1 + wacc) ** (t + 1))
    return pv


def calculate_terminal_value(
    terminal_eva: float, wacc: float, terminal_growth: float
) -> float:
    if terminal_growth >= wacc:
        raise ValueError("Terminal growth rate must be less than WACC")
    return (terminal_eva * (1 + terminal_growth)) / (wacc - terminal_growth)


def calculate_pv_terminal(
    terminal_value: float, wacc: float, projection_years: int
) -> float:
    return terminal_value / ((1 + wacc) ** projection_years)


def calculate_firm_value(
    current_invested_capital: float, pv_projected_eva: float, pv_terminal: float
) -> float:
    return current_invested_capital + pv_projected_eva + pv_terminal


def calculate_equity_value(
    firm_value: float, cash: float, total_debt: float, preferred_stock: float
) -> float:
    return firm_value - total_debt + cash - preferred_stock


def calculate_intrinsic_value(equity_value: float, shares_outstanding: float) -> float:
    if shares_outstanding <= 0:
        raise ValueError("Shares outstanding must be positive")
    return equity_value / shares_outstanding


def create_eva_graph() -> CalculationGraph:
    graph = CalculationGraph("EVA")

    graph.add_node("pv_projected_eva", calculate_pv_projected_eva)
    graph.add_node("terminal_value", calculate_terminal_value)

    def projection_years(projected_evas: list[float]) -> int:
        return len(projected_evas)

    graph.add_node("projection_years", projection_years)
    graph.add_node("pv_terminal", calculate_pv_terminal)
    graph.add_node("firm_value", calculate_firm_value)
    graph.add_node("equity_value", calculate_equity_value)
    graph.add_node("intrinsic_value", calculate_intrinsic_value)

    return graph
