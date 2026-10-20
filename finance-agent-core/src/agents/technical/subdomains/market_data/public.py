"""Stable ports and contracts for technical market data."""

from .application.multi_timeframe_fetch_service import (
    MultiTimeframeFetchRequest,
    fetch_timeseries_bundle,
)
from .application.ports import (
    IMarketDataProvider,
    MarketDataCacheConfig,
    MarketDataCacheMetadata,
    MarketDataOhlcvFetchResult,
    MarketDataProviderFailure,
    MarketDataRetryPolicy,
    MarketDataRiskFreeRateFetchResult,
    MarketDataTimeseriesBundleResult,
)
from .infrastructure.yahoo_market_data_provider import (
    YahooMarketDataProvider as _YahooMarketDataProvider,
)


def build_default_market_data_provider(
    *,
    cache: MarketDataCacheConfig = MarketDataCacheConfig(),
    retry_policy: MarketDataRetryPolicy = MarketDataRetryPolicy(),
) -> IMarketDataProvider:
    return _YahooMarketDataProvider(cache=cache, retry_policy=retry_policy)


__all__ = [
    "IMarketDataProvider",
    "MarketDataCacheConfig",
    "MarketDataCacheMetadata",
    "MarketDataOhlcvFetchResult",
    "MarketDataProviderFailure",
    "MarketDataRiskFreeRateFetchResult",
    "MarketDataRetryPolicy",
    "MarketDataTimeseriesBundleResult",
    "MultiTimeframeFetchRequest",
    "build_default_market_data_provider",
    "fetch_timeseries_bundle",
]
