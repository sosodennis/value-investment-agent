"""
Tools for the Executor node.

Contains mock data generators and will contain LLM extraction tools in production.
"""

from typing import Dict, Any


def generate_mock_saas_data(ticker: str) -> Dict[str, Any]:
    """
    Generate mock SaaS valuation parameters.
    
    In production, this would be replaced with LLM-based extraction
    from 10-K filings and financial statements.
    
    Args:
        ticker: Stock ticker symbol
        
    Returns:
        Dictionary matching SaaSParams schema
    """
    return {
        "ticker": ticker,
        "rationale": "Mocked extraction from 10-K",
        "initial_revenue": 100.0,
        "growth_rates": [0.20, 0.18, 0.15, 0.12, 0.10],
        "operating_margins": [0.10, 0.12, 0.15, 0.18, 0.20],
        "tax_rate": 0.21,
        "da_rates": [0.05] * 5,
        "capex_rates": [0.05] * 5,
        "wc_rates": [0.02] * 5,
        "sbc_rates": [0.10, 0.09, 0.08, 0.07, 0.06],
        "wacc": 0.10,
        "terminal_growth": 0.03
    }


def generate_mock_bank_data(ticker: str) -> Dict[str, Any]:
    """
    Generate mock bank valuation parameters.
    
    In production, this would be replaced with LLM-based extraction
    from bank financial statements and regulatory filings.
    
    Args:
        ticker: Stock ticker symbol
        
    Returns:
        Dictionary matching BankParams schema
    """
    return {
        "ticker": ticker,
        "rationale": "Mocked Bank Data",
        "initial_net_income": 500.0,
        "income_growth_rates": [0.05, 0.05, 0.04, 0.04, 0.03],
        "rwa_intensity": 0.02,  # 2% RoRWA
        "tier1_target_ratio": 0.12,
        "initial_capital": 6000.0,
        "cost_of_equity": 0.08,
        "terminal_growth": 0.02
    }
