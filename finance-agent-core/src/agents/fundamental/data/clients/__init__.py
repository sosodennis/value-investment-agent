"""Fundamental external clients package."""

from .market_data import MarketDataClient, MarketSnapshot, market_data_client

__all__ = ["MarketDataClient", "MarketSnapshot", "market_data_client"]
