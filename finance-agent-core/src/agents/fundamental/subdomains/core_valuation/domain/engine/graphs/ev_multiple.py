from __future__ import annotations

from ..core import CalculationGraph


def calculate_implied_ev(target_metric: float, multiple: float) -> float:
    return target_metric * multiple


def calculate_equity_value(
    implied_ev: float, cash: float, total_debt: float, preferred_stock: float
) -> float:
    return implied_ev - total_debt + cash - preferred_stock


def calculate_intrinsic_value(equity_value: float, shares_outstanding: float) -> float:
    if shares_outstanding <= 0:
        raise ValueError("Shares outstanding must be positive")
    return equity_value / shares_outstanding


def create_ev_multiple_graph() -> CalculationGraph:
    graph = CalculationGraph("EV_Multiple")

    graph.add_node("implied_ev", calculate_implied_ev)
    graph.add_node("equity_value", calculate_equity_value)
    graph.add_node("intrinsic_value", calculate_intrinsic_value)

    return graph
