"""
Debate tools package.
"""

from .analysis import (
    SycophancyDetector,
    calculate_pragmatic_verdict,
    compress_financial_data,
    compress_news_data,
    compress_ta_data,
    get_sycophancy_detector,
)
from .market_data import (
    calculate_capm_hurdle,
    get_current_risk_free_rate,
    get_dynamic_crash_impact,
    get_dynamic_payoff_map,
    get_stock_beta,
)

__all__ = [
    "get_stock_beta",
    "calculate_capm_hurdle",
    "get_current_risk_free_rate",
    "get_dynamic_crash_impact",
    "get_dynamic_payoff_map",
    "get_sycophancy_detector",
    "SycophancyDetector",
    "calculate_pragmatic_verdict",
    "compress_financial_data",
    "compress_news_data",
    "compress_ta_data",
]
