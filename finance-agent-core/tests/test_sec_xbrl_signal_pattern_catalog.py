from __future__ import annotations

from src.agents.fundamental.data.clients.sec_xbrl.rules.signal_pattern_catalog import (
    FORWARD_SIGNAL_PATTERN_CATALOG,
    METRIC_RETRIEVAL_QUERY,
    load_runtime_signal_catalog,
)


def test_default_runtime_catalog_includes_yaml_pattern_phrases() -> None:
    growth_patterns = FORWARD_SIGNAL_PATTERN_CATALOG["growth_outlook"]
    margin_patterns = FORWARD_SIGNAL_PATTERN_CATALOG["margin_outlook"]

    assert "raised full-year guidance" in growth_patterns.up
    assert "lowered full-year guidance" in growth_patterns.down
    assert "operating income margin expansion" in margin_patterns.up
    assert "costs to build and maintain infrastructure" in margin_patterns.down
    assert "gross margins will be subject to volatility and downward pressure" in (
        margin_patterns.down
    )
    assert (
        "net sales are expected to be between"
        in METRIC_RETRIEVAL_QUERY["growth_outlook"]
    )


def test_sector_runtime_catalog_merges_sector_overlay_terms() -> None:
    financials_catalog = load_runtime_signal_catalog(sector="financials")
    consumer_catalog = load_runtime_signal_catalog(sector="consumer_discretionary")

    assert (
        "net interest income"
        in financials_catalog.metric_retrieval_query["growth_outlook"]
    )
    assert "deposit margin compression" in financials_catalog.fls_skip_signal_phrases
    assert (
        "fulfillment network efficiencies"
        in consumer_catalog.metric_retrieval_query["margin_outlook"]
    )
