from __future__ import annotations

from src.agents.fundamental.infrastructure.market_data.investing_provider import (
    InvestingProvider,
)
from src.agents.fundamental.infrastructure.market_data.marketbeat_provider import (
    MarketBeatProvider,
)
from src.agents.fundamental.infrastructure.market_data.tipranks_provider import (
    TipRanksProvider,
)


def test_tipranks_provider_prefers_structured_json(monkeypatch) -> None:
    html = """
    <script type="application/json">
      {
        "averagePriceTarget": 255.2,
        "highPriceTarget": 300.0,
        "lowPriceTarget": 210.0,
        "numberOfAnalysts": 42
      }
    </script>
    """
    monkeypatch.setattr(
        "src.agents.fundamental.infrastructure.market_data.tipranks_provider.fetch_html",
        lambda _: html,
    )

    fetched = TipRanksProvider().fetch("AAPL")

    assert fetched.datums["target_mean_price"].value == 255.2
    assert fetched.datums["target_analyst_count"].value == 42.0
    assert "extract=structured_json" in (
        fetched.datums["target_mean_price"].source_detail or ""
    )
    assert fetched.warnings == ()


def test_investing_provider_resolves_search_url_and_extracts_structured_data(
    monkeypatch,
) -> None:
    search_html = '<a href="/equities/apple-consensus-estimates">AAPL</a>'
    page_html = """
    <script id="__NEXT_DATA__" type="application/json">
      {"props":{"pageProps":{"targetMeanPrice":238.1,"targetHighPrice":270.0,"targetLowPrice":205.0,"numberOfAnalysts":31}}}
    </script>
    """

    def _fake_fetch(url: str) -> str:
        if "search/?q=" in url:
            return search_html
        return page_html

    monkeypatch.setattr(
        "src.agents.fundamental.infrastructure.market_data.investing_provider.fetch_html",
        _fake_fetch,
    )

    fetched = InvestingProvider().fetch("AAPL")

    assert fetched.datums["target_mean_price"].value == 238.1
    assert fetched.datums["target_analyst_count"].value == 31.0
    assert "url=https://www.investing.com/equities/apple-consensus-estimates" in (
        fetched.datums["target_mean_price"].source_detail or ""
    )
    assert fetched.warnings == ()


def test_marketbeat_provider_surfaces_parse_missing_warning(monkeypatch) -> None:
    search_html = '<a href="/stocks/NASDAQ/AAPL/">AAPL</a>'
    page_html = "<div>Based on 25 analyst ratings.</div>"

    def _fake_fetch(url: str) -> str:
        if "stocks/?query=" in url:
            return search_html
        return page_html

    monkeypatch.setattr(
        "src.agents.fundamental.infrastructure.market_data.marketbeat_provider.fetch_html",
        _fake_fetch,
    )

    fetched = MarketBeatProvider().fetch("AAPL")

    assert fetched.datums["target_mean_price"].value is None
    assert fetched.datums["target_analyst_count"].value == 25.0
    assert any(
        "marketbeat target_mean_price parse missing" in msg for msg in fetched.warnings
    )
