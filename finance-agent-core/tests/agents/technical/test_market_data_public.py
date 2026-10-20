from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import src.agents.technical.subdomains.market_data.public as market_data_public
from src.agents.technical.subdomains.market_data.public import (
    IMarketDataProvider,
    MarketDataCacheConfig,
    MarketDataOhlcvFetchResult,
    MarketDataRetryPolicy,
    build_default_market_data_provider,
)


def test_default_factory_preserves_default_retry_and_cache_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_ohlcv(
        ticker_symbol: str,
        *,
        period: str,
        interval: str,
        cache_base_dir: str | None,
        cache_key_prefix: str,
        max_retries: int,
        retry_delay_seconds: float,
    ) -> MarketDataOhlcvFetchResult:
        captured.update(
            {
                "ticker_symbol": ticker_symbol,
                "period": period,
                "interval": interval,
                "cache_base_dir": cache_base_dir,
                "cache_key_prefix": cache_key_prefix,
                "max_retries": max_retries,
                "retry_delay_seconds": retry_delay_seconds,
            }
        )
        return MarketDataOhlcvFetchResult(data=None)

    monkeypatch.setattr(
        "src.agents.technical.subdomains.market_data.infrastructure.yahoo_market_data_provider.fetch_ohlcv",
        fake_fetch_ohlcv,
    )

    provider = build_default_market_data_provider()
    result = provider.fetch_ohlcv("AAPL", period="6mo", interval="1d")

    assert isinstance(result, MarketDataOhlcvFetchResult)
    assert captured == {
        "ticker_symbol": "AAPL",
        "period": "6mo",
        "interval": "1d",
        "cache_base_dir": None,
        "cache_key_prefix": "",
        "max_retries": 0,
        "retry_delay_seconds": 0.0,
    }
    assert "YahooMarketDataProvider" not in market_data_public.__all__
    assert not hasattr(market_data_public, "YahooMarketDataProvider")


def test_public_factory_applies_retry_policy_and_cache_namespace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    delays: list[float] = []

    class FakeTicker:
        splits = pd.Series(dtype=float)

        def history(
            self,
            *,
            period: str,
            interval: str,
            auto_adjust: bool,
        ) -> pd.DataFrame:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary provider failure")
            return pd.DataFrame(
                {
                    "Open": [10.0],
                    "High": [11.0],
                    "Low": [9.0],
                    "Close": [10.5],
                    "Volume": [100],
                },
                index=pd.to_datetime(["2026-10-19"], utc=True),
            )

    def fake_ticker(ticker_symbol: str) -> FakeTicker:
        return FakeTicker()

    monkeypatch.setattr(
        "src.agents.technical.subdomains.market_data.infrastructure.yahoo_ohlcv_provider.yf.Ticker",
        fake_ticker,
    )
    monkeypatch.setattr(
        "src.agents.technical.subdomains.market_data.infrastructure.yahoo_ohlcv_provider.time.sleep",
        delays.append,
    )

    provider: IMarketDataProvider = build_default_market_data_provider(
        cache=MarketDataCacheConfig(
            base_dir=str(tmp_path),
            namespace="decision_labeling",
        ),
        retry_policy=MarketDataRetryPolicy(max_retries=1, delay_seconds=0.25),
    )

    first_result = provider.fetch_ohlcv("AAPL", period="6mo", interval="1d")

    assert first_result.failure is None
    assert first_result.data is not None
    assert attempts == 2
    assert delays == [0.25]
    assert len(list(tmp_path.glob("decision_labeling_ohlcv_AAPL_1d_*.pkl"))) == 1

    cached_result = provider.fetch_ohlcv("AAPL", period="6mo", interval="1d")

    assert cached_result.cache is not None
    assert cached_result.cache.cache_hit is True
    assert attempts == 2


def test_public_configuration_rejects_unsafe_cache_namespace() -> None:
    with pytest.raises(ValueError, match="cache namespace"):
        MarketDataCacheConfig(namespace="../shared")


@pytest.mark.parametrize(
    ("max_retries", "delay_seconds"),
    [(-1, 0.0), (0, -0.1), (0, float("inf"))],
)
def test_retry_policy_rejects_invalid_values(
    max_retries: int,
    delay_seconds: float,
) -> None:
    with pytest.raises(ValueError):
        MarketDataRetryPolicy(
            max_retries=max_retries,
            delay_seconds=delay_seconds,
        )
