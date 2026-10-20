"""Stable market-data capability contracts and configured service."""

from .application.market_data_service import MarketDataService
from .domain.market_snapshot import MarketSnapshot
from .infrastructure.factory import (
    market_data_service as _configured_market_data_service,
)

market_data_service = _configured_market_data_service

__all__ = [
    "MarketDataService",
    "MarketSnapshot",
    "market_data_service",
]
