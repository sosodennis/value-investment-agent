import logging
import warnings
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from src.agents.technical.subdomains.market_data.application.ports import (
    MarketDataCacheMetadata,
    MarketDataOhlcvFetchResult,
    MarketDataProviderFailure,
)
from src.shared.kernel.tools.logger import get_logger, log_event

from .cache_service import MarketDataCache

logger = get_logger(__name__)

warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")


_CACHE_TTLS: dict[str, float] = {
    "1d": 60.0 * 60.0 * 24.0,
    "1wk": 60.0 * 60.0 * 24.0 * 7.0,
    "1h": 60.0 * 15.0,
}


def _bucket_for_interval(interval: str, now: datetime) -> str:
    if interval == "1wk":
        year, week, _ = now.isocalendar()
        return f"{year}-W{week:02d}"
    if interval == "1h":
        minute_bucket = (now.minute // 15) * 15
        return now.replace(minute=minute_bucket, second=0, microsecond=0).strftime(
            "%Y%m%d-%H%M"
        )
    return now.strftime("%Y%m%d")


def _build_cache_metadata(result, bucket: str | None) -> MarketDataCacheMetadata | None:
    if result is None:
        return None
    return MarketDataCacheMetadata(
        cache_hit=result.cache_hit,
        cache_age_seconds=result.cache_age_seconds,
        cache_bucket=bucket,
    )


def _normalize_index_utc(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame.index, pd.DatetimeIndex):
        return frame
    idx = frame.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    normalized = frame.copy()
    normalized.index = idx
    return normalized


def _normalize_series_index_utc(series: pd.Series) -> pd.Series:
    if not isinstance(series.index, pd.DatetimeIndex):
        series.index = pd.to_datetime(series.index, utc=True, errors="coerce")
        return series
    idx = series.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    series.index = idx
    return series


def fetch_ohlcv(
    ticker_symbol: str, *, period: str = "5y", interval: str = "1d"
) -> MarketDataOhlcvFetchResult:
    """Fetch OHLCV data and apply split adjustment to close prices."""
    try:
        now = datetime.now(timezone.utc)
        bucket = _bucket_for_interval(interval, now)
        ttl = _CACHE_TTLS.get(interval, 0.0)
        cache = MarketDataCache()
        cache_result = None
        if ttl > 0:
            cache_key = f"ohlcv_{ticker_symbol}_{interval}_{bucket}"
            cache_result = cache.get(
                key=cache_key,
                max_age_seconds=ttl,
                cache_bucket=bucket,
            )
            if cache_result.cache_hit and isinstance(cache_result.data, pd.DataFrame):
                log_event(
                    logger,
                    event="technical_ohlcv_cache_hit",
                    message="technical ohlcv cache hit",
                    fields={
                        "ticker": ticker_symbol,
                        "interval": interval,
                        "cache_hit": True,
                        "cache_age_seconds": cache_result.cache_age_seconds,
                        "cache_bucket": bucket,
                        "rows": len(cache_result.data),
                    },
                )
                return MarketDataOhlcvFetchResult(
                    data=cache_result.data,
                    cache=_build_cache_metadata(cache_result, bucket),
                )

        log_event(
            logger,
            event="technical_ohlcv_fetch_started",
            message="technical ohlcv fetch started",
            fields={
                "ticker": ticker_symbol,
                "period": period,
                "interval": interval,
                "cache_hit": False,
                "cache_bucket": bucket,
            },
        )
        ticker = yf.Ticker(ticker_symbol)

        df = ticker.history(period=period, interval=interval, auto_adjust=False)
        splits = ticker.splits

        if df.empty:
            log_event(
                logger,
                event="technical_ohlcv_fetch_empty",
                message="technical ohlcv fetch returned no data",
                level=logging.WARNING,
                error_code="TECHNICAL_OHLCV_EMPTY",
                fields={
                    "ticker": ticker_symbol,
                    "period": period,
                    "interval": interval,
                    "cache_bucket": bucket,
                },
            )
            return MarketDataOhlcvFetchResult(
                data=None,
                failure=MarketDataProviderFailure(
                    failure_code="TECHNICAL_OHLCV_EMPTY",
                    reason="empty_history",
                ),
                cache=_build_cache_metadata(cache_result, bucket),
            )

        df = _normalize_index_utc(df)
        df = df.sort_index()
        if not splits.empty:
            log_event(
                logger,
                event="technical_ohlcv_split_adjustment",
                message="technical ohlcv applying split adjustments",
                fields={"ticker": ticker_symbol, "split_count": len(splits)},
            )
            splits = _normalize_series_index_utc(splits)
            split_factors = pd.Series(1.0, index=df.index)
            for date, ratio in splits.items():
                if pd.isna(date):
                    continue
                split_factors.loc[df.index < date] *= ratio

            df["open"] = df["Open"] / split_factors
            df["high"] = df["High"] / split_factors
            df["low"] = df["Low"] / split_factors
            df["close"] = df["Close"] / split_factors
            df["price"] = df["close"]
        else:
            df["open"] = df["Open"]
            df["high"] = df["High"]
            df["low"] = df["Low"]
            df["close"] = df["Close"]
            df["price"] = df["close"]

        final_df = df[["open", "high", "low", "close", "price", "Volume"]].copy()
        final_df.rename(columns={"Volume": "volume"}, inplace=True)

        latest_date = final_df.index[-1]
        latest_price = final_df["price"].iloc[-1]
        latest_vol = final_df["volume"].iloc[-1]

        log_event(
            logger,
            event="technical_ohlcv_fetch_completed",
            message="technical ohlcv fetch completed",
            fields={
                "ticker": ticker_symbol,
                "interval": interval,
                "rows": len(final_df),
                "latest_date": str(latest_date),
                "latest_price": float(latest_price),
                "latest_volume": float(latest_vol),
                "cache_bucket": bucket,
            },
        )
        if ttl > 0:
            cache_key = f"ohlcv_{ticker_symbol}_{interval}_{bucket}"
            cache.set(key=cache_key, data=final_df)
        return MarketDataOhlcvFetchResult(
            data=final_df,
            cache=_build_cache_metadata(cache_result, bucket),
        )

    except Exception as exc:
        log_event(
            logger,
            event="technical_ohlcv_fetch_failed",
            message="technical ohlcv fetch failed",
            level=logging.ERROR,
            error_code="TECHNICAL_OHLCV_FETCH_FAILED",
            fields={
                "ticker": ticker_symbol,
                "period": period,
                "interval": interval,
                "exception": str(exc),
            },
        )
        return MarketDataOhlcvFetchResult(
            data=None,
            failure=MarketDataProviderFailure(
                failure_code="TECHNICAL_OHLCV_FETCH_FAILED",
                reason=str(exc),
            ),
        )


def fetch_daily_ohlcv(
    ticker_symbol: str, period: str = "5y"
) -> MarketDataOhlcvFetchResult:
    return fetch_ohlcv(ticker_symbol, period=period, interval="1d")
