"""Stable ports and contracts for technical market data."""

from .application.multi_timeframe_fetch_service import (
    MultiTimeframeFetchRequest,
    fetch_timeseries_bundle,
)
from .application.ports import (
    IMarketDataProvider,
    MarketDataCacheMetadata,
    MarketDataOhlcvFetchResult,
    MarketDataProviderFailure,
    MarketDataRiskFreeRateFetchResult,
    MarketDataTimeseriesBundleResult,
)

__all__ = [
    "IMarketDataProvider",
    "MarketDataCacheMetadata",
    "MarketDataOhlcvFetchResult",
    "MarketDataProviderFailure",
    "MarketDataRiskFreeRateFetchResult",
    "MarketDataTimeseriesBundleResult",
    "MultiTimeframeFetchRequest",
    "fetch_timeseries_bundle",
]
