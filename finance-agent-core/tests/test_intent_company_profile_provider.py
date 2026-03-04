from __future__ import annotations

from src.agents.intent.infrastructure.market_data.company_profile_provider import (
    get_company_profile,
)


class _TickerWithValidInfo:
    info = {
        "symbol": "AAPL",
        "longName": "Apple Inc.",
        "sector": "Technology",
        "industry": "Consumer Electronics",
    }


class _TickerMissingSymbol:
    info = {"longName": "Unknown Corp."}


def test_get_company_profile_success(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.agents.intent.infrastructure.market_data.company_profile_provider.yf.Ticker",
        lambda _ticker: _TickerWithValidInfo(),
    )

    lookup = get_company_profile("AAPL")

    assert lookup.failure_code is None
    assert lookup.failure_reason is None
    assert lookup.profile is not None
    assert lookup.profile.ticker == "AAPL"
    assert lookup.profile.name == "Apple Inc."


def test_get_company_profile_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.agents.intent.infrastructure.market_data.company_profile_provider.yf.Ticker",
        lambda _ticker: _TickerMissingSymbol(),
    )

    lookup = get_company_profile("AAPL")

    assert lookup.profile is None
    assert lookup.failure_code == "INTENT_PROFILE_NOT_FOUND"
    assert lookup.failure_reason == "profile missing symbol"


def test_get_company_profile_provider_error(monkeypatch) -> None:
    def _raise(_ticker: str) -> object:
        raise RuntimeError("provider down")

    monkeypatch.setattr(
        "src.agents.intent.infrastructure.market_data.company_profile_provider.yf.Ticker",
        _raise,
    )

    lookup = get_company_profile("AAPL")

    assert lookup.profile is None
    assert lookup.failure_code == "INTENT_PROFILE_PROVIDER_ERROR"
    assert lookup.failure_reason is not None
    assert "provider down" in lookup.failure_reason
