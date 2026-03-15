import logging
from datetime import datetime, timezone

import yfinance as yf

from src.agents.technical.subdomains.market_data.application.ports import (
    MarketDataCacheMetadata,
    MarketDataProviderFailure,
    MarketDataRiskFreeRateFetchResult,
)
from src.shared.kernel.tools.logger import get_logger, log_event

from .cache_service import MarketDataCache

logger = get_logger(__name__)
_CACHE_TTL_SECONDS = 60.0 * 60.0 * 24.0


def fetch_risk_free_series(period: str = "5y") -> MarketDataRiskFreeRateFetchResult:
    """Fetch historical daily risk-free rate series from ^TNX."""
    try:
        cache = MarketDataCache()
        now = datetime.now(timezone.utc)
        bucket = now.strftime("%Y%m%d")
        cache_key = f"risk_free_{bucket}"
        cache_result = cache.get(
            key=cache_key,
            max_age_seconds=_CACHE_TTL_SECONDS,
            cache_bucket=bucket,
        )
        if cache_result.cache_hit and cache_result.data is not None:
            log_event(
                logger,
                event="technical_risk_free_cache_hit",
                message="technical risk-free rate cache hit",
                fields={
                    "period": period,
                    "cache_hit": True,
                    "cache_age_seconds": cache_result.cache_age_seconds,
                    "cache_bucket": bucket,
                },
            )
            return MarketDataRiskFreeRateFetchResult(
                data=cache_result.data,
                cache=MarketDataCacheMetadata(
                    cache_hit=True,
                    cache_age_seconds=cache_result.cache_age_seconds,
                    cache_bucket=bucket,
                ),
            )

        log_event(
            logger,
            event="technical_risk_free_fetch_started",
            message="technical risk-free rate fetch started",
            fields={
                "period": period,
                "cache_hit": False,
                "cache_bucket": bucket,
            },
        )
        tnx = yf.Ticker("^TNX")
        hist = tnx.history(period=period, interval="1d")

        if hist.empty:
            log_event(
                logger,
                event="technical_risk_free_fetch_empty",
                message="technical risk-free rate fetch returned empty data",
                level=logging.WARNING,
                error_code="TECHNICAL_RISK_FREE_EMPTY",
                fields={
                    "period": period,
                    "cache_bucket": bucket,
                },
            )
            return MarketDataRiskFreeRateFetchResult(
                data=None,
                failure=MarketDataProviderFailure(
                    failure_code="TECHNICAL_RISK_FREE_EMPTY",
                    reason="empty_history",
                ),
                cache=MarketDataCacheMetadata(
                    cache_hit=False,
                    cache_age_seconds=cache_result.cache_age_seconds,
                    cache_bucket=bucket,
                ),
            )

        daily_rf = (hist["Close"] / 100.0) / 252.0
        daily_rf = daily_rf.ffill().fillna(0.0)
        daily_rf = daily_rf.clip(lower=0.0)

        cache.set(key=cache_key, data=daily_rf)
        log_event(
            logger,
            event="technical_risk_free_fetch_completed",
            message="technical risk-free rate fetch completed",
            fields={
                "period": period,
                "rows": len(daily_rf),
                "cache_bucket": bucket,
            },
        )
        return MarketDataRiskFreeRateFetchResult(
            data=daily_rf,
            cache=MarketDataCacheMetadata(
                cache_hit=False,
                cache_age_seconds=cache_result.cache_age_seconds,
                cache_bucket=bucket,
            ),
        )

    except Exception as exc:
        log_event(
            logger,
            event="technical_risk_free_fetch_failed",
            message="technical risk-free rate fetch failed",
            level=logging.ERROR,
            error_code="TECHNICAL_RISK_FREE_FETCH_FAILED",
            fields={"period": period, "exception": str(exc)},
        )
        return MarketDataRiskFreeRateFetchResult(
            data=None,
            failure=MarketDataProviderFailure(
                failure_code="TECHNICAL_RISK_FREE_FETCH_FAILED",
                reason=str(exc),
            ),
        )
