from __future__ import annotations

from ..core import CalculationGraph


def calculate_enterprise_value(ffo: float, ffo_multiple: float) -> float:
    return ffo * ffo_multiple


def calculate_equity_value(
    enterprise_value: float, cash: float, total_debt: float, preferred_stock: float
) -> float:
    return enterprise_value - total_debt + cash - preferred_stock


def calculate_intrinsic_value(equity_value: float, shares_outstanding: float) -> float:
    if shares_outstanding <= 0:
        raise ValueError("Shares outstanding must be positive")
    return equity_value / shares_outstanding


def create_reit_ffo_graph() -> CalculationGraph:
    graph = CalculationGraph("REIT_FFO")

    graph.add_node("enterprise_value", calculate_enterprise_value)
    graph.add_node("equity_value", calculate_equity_value)
    graph.add_node("intrinsic_value", calculate_intrinsic_value)

    return graph
