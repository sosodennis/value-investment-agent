from __future__ import annotations

from datetime import datetime, timezone

from src.agents.fundamental.market_data.domain.consensus_anchor_aggregator import (
    FREE_CONSENSUS_AGGREGATE_SOURCE,
    build_target_consensus_anchor_datums,
)
from src.agents.fundamental.market_data.domain.provider_contracts import (
    MarketDatum,
)


def test_build_target_consensus_anchor_uses_cross_source_median() -> None:
    now = datetime(2026, 3, 5, tzinfo=timezone.utc)
    provider_results = {
        "tipranks": {
            "target_mean_price": MarketDatum(205.0, "tipranks", "2026-03-05T00:00:00Z"),
            "target_analyst_count": MarketDatum(
                38.0, "tipranks", "2026-03-05T00:00:00Z"
            ),
        },
        "investing": {
            "target_mean_price": MarketDatum(
                198.0, "investing", "2026-03-05T00:00:00Z"
            ),
            "target_analyst_count": MarketDatum(
                30.0, "investing", "2026-03-05T00:00:00Z"
            ),
        },
        "yfinance": {
            "target_mean_price": MarketDatum(220.0, "yfinance", "2026-03-05T00:00:00Z"),
        },
    }

    result = build_target_consensus_anchor_datums(
        provider_results=provider_results,
        now=now,
    )

    datum = result.datums.get("target_mean_price")
    assert datum is not None
    assert datum.source == FREE_CONSENSUS_AGGREGATE_SOURCE
    assert datum.value == 205.0
    assert datum.horizon == "12m"
    assert "source_count=3" in (datum.source_detail or "")


def test_build_target_consensus_anchor_filters_low_coverage_sources() -> None:
    now = datetime(2026, 3, 5, tzinfo=timezone.utc)
    provider_results = {
        "tipranks": {
            "target_mean_price": MarketDatum(205.0, "tipranks", "2026-03-05T00:00:00Z"),
            "target_analyst_count": MarketDatum(
                4.0, "tipranks", "2026-03-05T00:00:00Z"
            ),
        },
        "investing": {
            "target_mean_price": MarketDatum(
                198.0, "investing", "2026-03-05T00:00:00Z"
            ),
            "target_analyst_count": MarketDatum(
                30.0, "investing", "2026-03-05T00:00:00Z"
            ),
        },
        "yfinance": {
            "target_mean_price": MarketDatum(220.0, "yfinance", "2026-03-05T00:00:00Z"),
        },
    }

    result = build_target_consensus_anchor_datums(
        provider_results=provider_results,
        now=now,
    )

    datum = result.datums.get("target_mean_price")
    assert datum is not None
    assert datum.value == 209.0
    assert any(
        "tipranks target_mean_price filtered by analyst_count" in w
        for w in result.warnings
    )


def test_build_target_consensus_anchor_skips_on_insufficient_sources(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FUNDAMENTAL_TARGET_CONSENSUS_MIN_SOURCES", "3")
    now = datetime(2026, 3, 5, tzinfo=timezone.utc)
    provider_results = {
        "yfinance": {
            "target_mean_price": MarketDatum(220.0, "yfinance", "2026-03-05T00:00:00Z"),
        },
        "tipranks": {
            "target_mean_price": MarketDatum(205.0, "tipranks", "2026-03-05T00:00:00Z"),
            "target_analyst_count": MarketDatum(
                4.0, "tipranks", "2026-03-05T00:00:00Z"
            ),
        },
    }

    result = build_target_consensus_anchor_datums(
        provider_results=provider_results,
        now=now,
    )

    assert result.datums == {}
    assert any("insufficient_sources=1" in warning for warning in result.warnings)
