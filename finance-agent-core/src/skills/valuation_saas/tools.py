from typing import Any, Dict
from ...engine.graphs.saas_fcff import create_saas_graph
from .schemas import SaaSParams

def calculate_saas_valuation(params: SaaSParams) -> Dict[str, Any]:
    """
    Executes the SaaS FCFF Valuation Graph using provided parameters.
    """
    graph = create_saas_graph()
    
    inputs = {
        "initial_revenue": params.initial_revenue,
        "growth_rates": params.growth_rates,
        "operating_margins": params.operating_margins,
        "tax_rate": params.tax_rate,
        "da_rates": params.da_rates,
        "capex_rates": params.capex_rates,
        "wc_rates": params.wc_rates,
        "sbc_rates": params.sbc_rates,
        "wacc": params.wacc,
        "terminal_growth": params.terminal_growth
    }
    
    try:
        results = graph.calculate(inputs)
        return {
            "ticker": params.ticker,
            "equity_value": results["equity_value"],
            "details": results # Return full trace if needed
        }
    except Exception as e:
        return {"error": str(e)}
