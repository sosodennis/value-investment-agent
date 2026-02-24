from __future__ import annotations

from src.agents.fundamental.data.clients.market_data import (
    DEFAULT_BETA,
    DEFAULT_RISK_FREE_RATE,
    MarketDataClient,
)
from src.agents.fundamental.data.clients.market_providers import ProviderFetch
from src.agents.fundamental.data.ports import MarketDatum


class _StaticProvider:
    def __init__(
        self,
        *,
        name: str,
        license_note: str,
        datums: dict[str, MarketDatum],
    ) -> None:
        self.name = name
        self.license_note = license_note
        self._datums = datums
        self.calls = 0

    def fetch(self, ticker_symbol: str) -> ProviderFetch:
        del ticker_symbol
        self.calls += 1
        return ProviderFetch(datums=dict(self._datums))


class _FailingProvider:
    def __init__(self, *, name: str = "broken") -> None:
        self.name = name
        self.license_note = "broken provider"
        self.calls = 0

    def fetch(self, ticker_symbol: str) -> ProviderFetch:
        del ticker_symbol
        self.calls += 1
        raise RuntimeError("network down")


def test_market_data_client_prefers_macro_provider_for_risk_free_rate() -> None:
    yahoo = _StaticProvider(
        name="yfinance",
        license_note="yahoo license",
        datums={
            "current_price": MarketDatum(123.4, "yfinance", "2026-02-23T00:00:00Z"),
            "market_cap": MarketDatum(50_000_000.0, "yfinance", "2026-02-23T00:00:00Z"),
            "shares_outstanding": MarketDatum(
                100_000.0, "yfinance", "2026-02-23T00:00:00Z"
            ),
            "beta": MarketDatum(1.2, "yfinance", "2026-02-23T00:00:00Z"),
            "risk_free_rate": MarketDatum(0.041, "yfinance", "2026-02-23T00:00:00Z"),
            "consensus_growth_rate": MarketDatum(
                0.11, "yfinance", "2026-02-23T00:00:00Z"
            ),
            "target_mean_price": MarketDatum(140.0, "yfinance", "2026-02-23T00:00:00Z"),
        },
    )
    fred = _StaticProvider(
        name="fred",
        license_note="fred license",
        datums={
            "risk_free_rate": MarketDatum(0.043, "fred", "2026-02-22"),
        },
    )

    client = MarketDataClient(ttl_seconds=120, max_retries=0, providers=(yahoo, fred))
    snapshot = client.get_market_snapshot("EXM")

    assert snapshot.risk_free_rate == 0.043
    assert snapshot.current_price == 123.4
    assert snapshot.shares_outstanding == 100_000.0
    assert snapshot.provider == "yfinance"
    assert snapshot.market_datums["risk_free_rate"]["source"] == "fred"
    assert snapshot.market_datums["current_price"]["source"] == "yfinance"
    assert snapshot.license_note is not None
    assert "yahoo license" in snapshot.license_note
    assert "fred license" in snapshot.license_note


def test_market_data_client_uses_cache_within_ttl() -> None:
    yahoo = _StaticProvider(
        name="yfinance",
        license_note="yahoo license",
        datums={
            "current_price": MarketDatum(99.0, "yfinance", "2026-02-23T00:00:00Z"),
            "shares_outstanding": MarketDatum(
                1_000.0, "yfinance", "2026-02-23T00:00:00Z"
            ),
        },
    )
    fred = _StaticProvider(
        name="fred",
        license_note="fred license",
        datums={"risk_free_rate": MarketDatum(0.04, "fred", "2026-02-23")},
    )

    client = MarketDataClient(ttl_seconds=120, max_retries=0, providers=(yahoo, fred))
    _ = client.get_market_snapshot("EXM")
    _ = client.get_market_snapshot("EXM")

    assert yahoo.calls == 1
    assert fred.calls == 1


def test_market_data_client_returns_policy_defaults_on_failure() -> None:
    failing = _FailingProvider()

    client = MarketDataClient(ttl_seconds=120, max_retries=0, providers=(failing,))
    snapshot = client.get_market_snapshot("EXM")

    assert snapshot.beta == DEFAULT_BETA
    assert snapshot.risk_free_rate == DEFAULT_RISK_FREE_RATE
    assert snapshot.shares_outstanding is None
    assert snapshot.source_warnings
    assert snapshot.market_datums["beta"]["source"] == "policy_default"
    assert snapshot.market_datums["risk_free_rate"]["source"] == "policy_default"
