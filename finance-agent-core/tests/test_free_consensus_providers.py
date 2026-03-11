from __future__ import annotations

from pathlib import Path

from src.agents.fundamental.subdomains.market_data.infrastructure.investing_provider import (
    InvestingProvider,
)
from src.agents.fundamental.subdomains.market_data.infrastructure.marketbeat_provider import (
    MarketBeatProvider,
)
from src.agents.fundamental.subdomains.market_data.infrastructure.tipranks_provider import (
    TipRanksProvider,
)


def _fixture_text(name: str) -> str:
    fixture_path = (
        Path(__file__).resolve().parent / "fixtures" / "free_consensus" / name
    )
    return fixture_path.read_text(encoding="utf-8")


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
        "src.agents.fundamental.subdomains.market_data.infrastructure.tipranks_provider.fetch_html",
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
        "src.agents.fundamental.subdomains.market_data.infrastructure.investing_provider.fetch_html",
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
        "src.agents.fundamental.subdomains.market_data.infrastructure.marketbeat_provider.fetch_html",
        _fake_fetch,
    )

    fetched = MarketBeatProvider().fetch("AAPL")

    assert fetched.datums["target_mean_price"].value is None
    assert fetched.datums["target_analyst_count"].value == 25.0
    assert any(
        "marketbeat target_mean_price parse missing" in msg for msg in fetched.warnings
    )


def test_tipranks_provider_parses_text_fallback_fixture(monkeypatch) -> None:
    page_html = _fixture_text("tipranks_page_text_variant.html")
    monkeypatch.setattr(
        "src.agents.fundamental.subdomains.market_data.infrastructure.tipranks_provider.fetch_html",
        lambda _: page_html,
    )

    fetched = TipRanksProvider().fetch("AAPL")

    assert fetched.datums["target_mean_price"].value == 255.2
    assert fetched.datums["target_high_price"].value == 300.0
    assert fetched.datums["target_low_price"].value == 210.0
    assert fetched.datums["target_analyst_count"].value == 42.0
    assert "extract=text_pattern" in (
        fetched.datums["target_mean_price"].source_detail or ""
    )
    assert fetched.warnings == ()


def test_investing_provider_parses_text_fallback_fixture(monkeypatch) -> None:
    search_html = _fixture_text("investing_search_variant.html")
    page_html = _fixture_text("investing_page_text_variant.html")

    def _fake_fetch(url: str) -> str:
        if "search/?q=" in url:
            return search_html
        return page_html

    monkeypatch.setattr(
        "src.agents.fundamental.subdomains.market_data.infrastructure.investing_provider.fetch_html",
        _fake_fetch,
    )

    fetched = InvestingProvider().fetch("AAPL")

    assert fetched.datums["target_mean_price"].value == 238.1
    assert fetched.datums["target_high_price"].value == 270.0
    assert fetched.datums["target_low_price"].value == 205.0
    assert fetched.datums["target_analyst_count"].value == 31.0
    assert "extract=text_pattern" in (
        fetched.datums["target_mean_price"].source_detail or ""
    )
    assert fetched.warnings == ()


def test_marketbeat_provider_parses_consensus_text_fallback_fixture(
    monkeypatch,
) -> None:
    search_html = _fixture_text("marketbeat_search_variant.html")
    page_html = _fixture_text("marketbeat_page_text_variant.html")

    def _fake_fetch(url: str) -> str:
        if "stocks/?query=" in url:
            return search_html
        return page_html

    monkeypatch.setattr(
        "src.agents.fundamental.subdomains.market_data.infrastructure.marketbeat_provider.fetch_html",
        _fake_fetch,
    )

    fetched = MarketBeatProvider().fetch("AAPL")

    assert fetched.datums["target_mean_price"].value == 251.4
    assert fetched.datums["target_high_price"].value == 289.0
    assert fetched.datums["target_low_price"].value == 220.0
    assert fetched.datums["target_analyst_count"].value == 27.0
    assert "extract=text_pattern" in (
        fetched.datums["target_mean_price"].source_detail or ""
    )
    assert fetched.warnings == ()
