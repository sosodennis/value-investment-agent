from typing import Any

from ...engine.graphs.bank_ddm import create_bank_graph
from .schemas import BankParams


def calculate_bank_valuation(params: BankParams) -> dict[str, Any]:
    """
    Executes the Bank DDM Valuation Graph.
    """
    graph = create_bank_graph()

    inputs = {
        "initial_net_income": params.initial_net_income,
        "income_growth_rates": params.income_growth_rates,
        "rwa_intensity": params.rwa_intensity,
        "tier1_target_ratio": params.tier1_target_ratio,
        "initial_capital": params.initial_capital,
        "cost_of_equity": params.cost_of_equity,
        "terminal_growth": params.terminal_growth,
    }

    try:
        results = graph.calculate(inputs)
        return {
            "ticker": params.ticker,
            "equity_value": results["equity_value"],
            "details": results,
        }
    except Exception as e:
        return {"error": str(e)}
