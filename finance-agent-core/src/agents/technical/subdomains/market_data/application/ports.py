from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from src.agents.technical.domain.shared.timeframe import TimeframeCode


@dataclass(frozen=True)
class MarketDataProviderFailure:
    failure_code: str
    reason: str | None = None
    http_status: int | None = None


@dataclass(frozen=True)
class MarketDataCacheMetadata:
    cache_hit: bool
    cache_age_seconds: float | None = None
    cache_bucket: str | None = None


@dataclass(frozen=True)
class MarketDataCacheConfig:
    base_dir: str | None = None
    namespace: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]*", self.namespace):
            raise ValueError(
                "cache namespace must contain only letters, digits, '_' or '-'"
            )


@dataclass(frozen=True)
class MarketDataRetryPolicy:
    max_retries: int = 0
    delay_seconds: float = 0.0

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
            or self.max_retries < 0
        ):
            raise ValueError("max_retries must be a non-negative integer")
        if (
            isinstance(self.delay_seconds, bool)
            or not isinstance(self.delay_seconds, int | float)
            or not math.isfinite(self.delay_seconds)
            or self.delay_seconds < 0
        ):
            raise ValueError("delay_seconds must be finite and non-negative")


@dataclass(frozen=True)
class MarketDataOhlcvFetchResult:
    data: pd.DataFrame | None
    failure: MarketDataProviderFailure | None = None
    cache: MarketDataCacheMetadata | None = None


@dataclass(frozen=True)
class MarketDataRiskFreeRateFetchResult:
    data: pd.Series | None
    failure: MarketDataProviderFailure | None = None
    cache: MarketDataCacheMetadata | None = None


@dataclass(frozen=True)
class MarketDataTimeseriesBundleResult:
    frames: dict[TimeframeCode, pd.DataFrame]
    degraded_reasons: list[str]
    failures: dict[TimeframeCode, MarketDataProviderFailure] | None = None
    cache: dict[TimeframeCode, MarketDataCacheMetadata] | None = None


class IMarketDataProvider(Protocol):
    def fetch_ohlcv(
        self,
        ticker_symbol: str,
        *,
        period: str = "5y",
        interval: str = "1d",
    ) -> MarketDataOhlcvFetchResult: ...

    def fetch_risk_free_series(
        self, period: str = "5y"
    ) -> MarketDataRiskFreeRateFetchResult: ...
