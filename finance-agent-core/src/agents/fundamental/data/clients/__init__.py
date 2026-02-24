"""Fundamental external clients package."""

from .market_data import MarketDataClient, MarketSnapshot, market_data_client
from .market_providers import FREDMacroProvider, YahooFinanceProvider

__all__ = [
    "MarketDataClient",
    "MarketSnapshot",
    "market_data_client",
    "YahooFinanceProvider",
    "FREDMacroProvider",
]
