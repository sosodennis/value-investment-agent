from __future__ import annotations

from ..core import CalculationGraph


def calculate_maintenance_capex(
    depreciation_and_amortization: float, maintenance_capex_ratio: float
) -> float:
    if depreciation_and_amortization < 0:
        raise ValueError("Depreciation and amortization cannot be negative")
    if maintenance_capex_ratio < 0:
        raise ValueError("Maintenance capex ratio cannot be negative")
    return depreciation_and_amortization * maintenance_capex_ratio


def calculate_affo(ffo: float, maintenance_capex: float) -> float:
    return ffo - maintenance_capex


def calculate_enterprise_value(affo: float, ffo_multiple: float) -> float:
    return affo * ffo_multiple


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

    graph.add_node("maintenance_capex", calculate_maintenance_capex)
    graph.add_node("affo", calculate_affo)
    graph.add_node("enterprise_value", calculate_enterprise_value)
    graph.add_node("equity_value", calculate_equity_value)
    graph.add_node("intrinsic_value", calculate_intrinsic_value)

    return graph
