from __future__ import annotations

from src.agents.fundamental.data.clients import market_data as market_data_module
from src.agents.fundamental.data.clients.market_data import (
    DEFAULT_BETA,
    DEFAULT_RISK_FREE_RATE,
    MarketDataClient,
)


def test_market_data_client_normalizes_risk_free_rate(monkeypatch) -> None:
    class _FakeTicker:
        def __init__(self, symbol: str):
            self._symbol = symbol

        @property
        def info(self) -> dict[str, object]:
            if self._symbol == "^TNX":
                return {"regularMarketPrice": 4.25}
            return {
                "currentPrice": 123.4,
                "marketCap": 50_000_000.0,
                "sharesOutstanding": 100_000.0,
                "beta": 1.2,
                "revenueGrowth": 0.11,
                "targetMeanPrice": 140.0,
            }

    monkeypatch.setattr(market_data_module.yf, "Ticker", _FakeTicker)

    client = MarketDataClient(ttl_seconds=120, max_retries=0)
    snapshot = client.get_market_snapshot("EXM")

    assert snapshot.risk_free_rate == 0.0425
    assert snapshot.shares_outstanding == 100_000.0
    assert snapshot.current_price == 123.4
    assert snapshot.provider == "yfinance"


def test_market_data_client_uses_cache_within_ttl(monkeypatch) -> None:
    call_count = {"count": 0}

    class _FakeTicker:
        def __init__(self, symbol: str):
            self._symbol = symbol

        @property
        def info(self) -> dict[str, object]:
            call_count["count"] += 1
            if self._symbol == "^TNX":
                return {"regularMarketPrice": 4.0}
            return {"currentPrice": 99.0, "sharesOutstanding": 1000.0}

    monkeypatch.setattr(market_data_module.yf, "Ticker", _FakeTicker)

    client = MarketDataClient(ttl_seconds=120, max_retries=0)
    _ = client.get_market_snapshot("EXM")
    _ = client.get_market_snapshot("EXM")

    # First fetch calls: EXM + ^TNX. Second call should hit cache.
    assert call_count["count"] == 2


def test_market_data_client_returns_fallback_on_failure(monkeypatch) -> None:
    class _FailingTicker:
        def __init__(self, symbol: str):
            self._symbol = symbol

        @property
        def info(self) -> dict[str, object]:
            raise RuntimeError("network down")

    monkeypatch.setattr(market_data_module.yf, "Ticker", _FailingTicker)

    client = MarketDataClient(ttl_seconds=120, max_retries=0)
    snapshot = client.get_market_snapshot("EXM")

    assert snapshot.beta == DEFAULT_BETA
    assert snapshot.risk_free_rate == DEFAULT_RISK_FREE_RATE
    assert snapshot.shares_outstanding is None
    assert snapshot.source_warnings
