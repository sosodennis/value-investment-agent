from __future__ import annotations

from ..core import CalculationGraph


def calculate_pv_projected_ri(
    projected_residual_incomes: list[float], required_return: float
) -> float:
    pv = 0.0
    for t, ri in enumerate(projected_residual_incomes):
        pv += ri / ((1 + required_return) ** (t + 1))
    return pv


def calculate_terminal_value(
    terminal_residual_income: float, required_return: float, terminal_growth: float
) -> float:
    if terminal_growth >= required_return:
        raise ValueError("Terminal growth rate must be less than required return")
    return (terminal_residual_income * (1 + terminal_growth)) / (
        required_return - terminal_growth
    )


def calculate_pv_terminal(
    terminal_value: float, required_return: float, projection_years: int
) -> float:
    return terminal_value / ((1 + required_return) ** projection_years)


def calculate_total_value(
    current_book_value: float, pv_projected_ri: float, pv_terminal: float
) -> float:
    return current_book_value + pv_projected_ri + pv_terminal


def calculate_intrinsic_value(total_value: float, shares_outstanding: float) -> float:
    if shares_outstanding <= 0:
        raise ValueError("Shares outstanding must be positive")
    return total_value / shares_outstanding


def create_residual_income_graph() -> CalculationGraph:
    graph = CalculationGraph("Residual_Income")

    graph.add_node("pv_projected_ri", calculate_pv_projected_ri)
    graph.add_node("terminal_value", calculate_terminal_value)

    def projection_years(projected_residual_incomes: list[float]) -> int:
        return len(projected_residual_incomes)

    graph.add_node("projection_years", projection_years)
    graph.add_node("pv_terminal", calculate_pv_terminal)
    graph.add_node("total_value", calculate_total_value)
    graph.add_node("intrinsic_value", calculate_intrinsic_value)

    return graph
