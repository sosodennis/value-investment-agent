from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.agents.fundamental.subdomains.market_data.application.market_data_service import (
    DEFAULT_BETA,
    DEFAULT_RISK_FREE_RATE,
    MarketDataService,
    recompute_market_snapshot_staleness,
)
from src.agents.fundamental.subdomains.market_data.application.ports import (
    ProviderFetch,
)
from src.agents.fundamental.subdomains.market_data.domain.consensus_anchor_aggregator import (
    FREE_CONSENSUS_AGGREGATE_SOURCE,
)
from src.agents.fundamental.subdomains.market_data.domain.market_datum import (
    MarketDatum,
)


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


class _CodedFailingProvider:
    def __init__(self, *, name: str, message: str) -> None:
        self.name = name
        self.license_note = f"{name} provider"
        self._message = message

    def fetch(self, ticker_symbol: str) -> ProviderFetch:
        del ticker_symbol
        raise RuntimeError(self._message)


def test_market_data_service_prefers_macro_provider_for_risk_free_rate() -> None:
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

    service = MarketDataService(ttl_seconds=120, max_retries=0, providers=(yahoo, fred))
    snapshot = service.get_market_snapshot("EXM")

    assert snapshot.risk_free_rate == 0.043
    assert snapshot.current_price == 123.4
    assert snapshot.shares_outstanding == 100_000.0
    assert snapshot.provider == "yfinance"
    assert snapshot.market_datums["risk_free_rate"]["source"] == "fred"
    assert snapshot.market_datums["current_price"]["source"] == "yfinance"
    assert snapshot.market_datums["shares_outstanding"]["shares_scope"] == "unknown"
    assert snapshot.license_note is not None
    assert "yahoo license" in snapshot.license_note
    assert "fred license" in snapshot.license_note


def test_market_data_service_uses_cache_within_ttl() -> None:
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

    service = MarketDataService(ttl_seconds=120, max_retries=0, providers=(yahoo, fred))
    _ = service.get_market_snapshot("EXM")
    _ = service.get_market_snapshot("EXM")

    assert yahoo.calls == 1
    assert fred.calls == 1


def test_market_data_service_returns_policy_defaults_on_failure() -> None:
    failing = _FailingProvider()

    service = MarketDataService(ttl_seconds=120, max_retries=0, providers=(failing,))
    snapshot = service.get_market_snapshot("EXM")

    assert snapshot.beta == DEFAULT_BETA
    assert snapshot.risk_free_rate == DEFAULT_RISK_FREE_RATE
    assert snapshot.shares_outstanding is None
    assert snapshot.source_warnings
    assert snapshot.market_datums["beta"]["source"] == "policy_default"
    assert snapshot.market_datums["risk_free_rate"]["source"] == "policy_default"


def test_market_data_service_marks_shares_staleness_fields() -> None:
    yahoo = _StaticProvider(
        name="yfinance",
        license_note="yahoo license",
        datums={
            "current_price": MarketDatum(90.0, "yfinance", "2026-01-01T00:00:00Z"),
            "shares_outstanding": MarketDatum(
                1_000.0, "yfinance", "2026-01-01T00:00:00Z"
            ),
        },
    )
    fred = _StaticProvider(
        name="fred",
        license_note="fred license",
        datums={"risk_free_rate": MarketDatum(0.04, "fred", "2026-01-01")},
    )

    service = MarketDataService(ttl_seconds=120, max_retries=0, providers=(yahoo, fred))
    snapshot = service.get_market_snapshot("EXM")

    assert snapshot.market_stale_max_days == 5
    assert snapshot.shares_outstanding_is_stale is True
    assert isinstance(snapshot.shares_outstanding_staleness_days, int)
    staleness = snapshot.market_datums["shares_outstanding"].get("staleness")
    assert isinstance(staleness, dict)
    assert staleness.get("is_stale") is True


def test_market_data_service_uses_strict_staleness_for_long_run_growth_anchor() -> None:
    stale_as_of = (datetime.now(timezone.utc) - timedelta(days=154)).isoformat()
    yahoo = _StaticProvider(
        name="yfinance",
        license_note="yahoo license",
        datums={
            "current_price": MarketDatum(90.0, "yfinance", stale_as_of),
            "shares_outstanding": MarketDatum(1_000.0, "yfinance", stale_as_of),
        },
    )
    fred = _StaticProvider(
        name="fred",
        license_note="fred license",
        datums={
            "risk_free_rate": MarketDatum(0.04, "fred", stale_as_of),
            "long_run_growth_anchor": MarketDatum(
                0.014,
                "fred",
                stale_as_of,
                update_cadence_days=90,
            ),
        },
    )

    service = MarketDataService(ttl_seconds=120, max_retries=0, providers=(yahoo, fred))
    snapshot = service.get_market_snapshot("EXM")

    long_run_staleness = snapshot.market_datums["long_run_growth_anchor"].get(
        "staleness"
    )
    assert isinstance(long_run_staleness, dict)
    assert long_run_staleness.get("max_days") == 90
    assert long_run_staleness.get("is_stale") is True
    assert "long_run_growth_anchor:stale" in snapshot.quality_flags

    shares_staleness = snapshot.market_datums["shares_outstanding"].get("staleness")
    assert isinstance(shares_staleness, dict)
    assert shares_staleness.get("max_days") == 5
    assert shares_staleness.get("is_stale") is True


def test_recompute_market_snapshot_staleness_reuses_market_data_policy() -> None:
    as_of_now = datetime(2026, 3, 8, tzinfo=timezone.utc)
    snapshot = {
        "as_of": as_of_now.isoformat(),
        "market_stale_max_days": 5,
        "market_datums": {
            "shares_outstanding": {
                "value": 1000.0,
                "source": "yfinance",
                "as_of": "2026-02-20T00:00:00Z",
                "quality_flags": [],
            },
            "long_run_growth_anchor": {
                "value": 0.014,
                "source": "fred",
                "as_of": "2025-10-05T00:00:00Z",
                "update_cadence_days": 90,
                "quality_flags": [],
            },
        },
    }
    recomputed = recompute_market_snapshot_staleness(snapshot, now=as_of_now)

    assert isinstance(recomputed, dict)
    shares_staleness = recomputed["market_datums"]["shares_outstanding"]["staleness"]
    assert shares_staleness["max_days"] == 5
    assert shares_staleness["is_stale"] is True
    assert recomputed["shares_outstanding_is_stale"] is True

    anchor_staleness = recomputed["market_datums"]["long_run_growth_anchor"][
        "staleness"
    ]
    assert anchor_staleness["max_days"] == 90
    assert anchor_staleness["is_stale"] is True


def test_market_data_service_prefers_consensus_aggregate_for_target_mean_price() -> (
    None
):
    yfinance = _StaticProvider(
        name="yfinance",
        license_note="yahoo license",
        datums={
            "current_price": MarketDatum(90.0, "yfinance", "2026-03-05T00:00:00Z"),
            "shares_outstanding": MarketDatum(
                1_000.0, "yfinance", "2026-03-05T00:00:00Z"
            ),
            "beta": MarketDatum(1.1, "yfinance", "2026-03-05T00:00:00Z"),
            "risk_free_rate": MarketDatum(0.04, "yfinance", "2026-03-05T00:00:00Z"),
            "target_mean_price": MarketDatum(220.0, "yfinance", "2026-03-05T00:00:00Z"),
        },
    )
    tipranks = _StaticProvider(
        name="tipranks",
        license_note="tipranks license",
        datums={
            "target_mean_price": MarketDatum(
                200.0,
                "tipranks",
                "2026-03-05T00:00:00Z",
            ),
            "target_analyst_count": MarketDatum(
                30.0,
                "tipranks",
                "2026-03-05T00:00:00Z",
            ),
        },
    )
    investing = _StaticProvider(
        name="investing",
        license_note="investing license",
        datums={
            "target_mean_price": MarketDatum(
                210.0,
                "investing",
                "2026-03-05T00:00:00Z",
            ),
            "target_analyst_count": MarketDatum(
                24.0,
                "investing",
                "2026-03-05T00:00:00Z",
            ),
        },
    )

    service = MarketDataService(
        ttl_seconds=120,
        max_retries=0,
        providers=(yfinance, tipranks, investing),
    )
    snapshot = service.get_market_snapshot("EXM")

    assert snapshot.target_mean_price == 210.0
    assert snapshot.market_datums["target_mean_price"]["source"] == (
        FREE_CONSENSUS_AGGREGATE_SOURCE
    )
    assert snapshot.target_consensus_applied is True
    assert snapshot.target_consensus_source_count == 3
    assert snapshot.target_consensus_sources == ("tipranks", "investing", "yfinance")
    assert snapshot.target_consensus_fallback_reason is None
    assert snapshot.target_consensus_warning_codes == ()
    assert snapshot.target_consensus_quality_bucket == "high"
    assert snapshot.target_consensus_confidence_weight == 1.0


def test_market_data_service_falls_back_to_yfinance_target_when_consensus_insufficient(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FUNDAMENTAL_TARGET_CONSENSUS_MIN_SOURCES", "3")
    yfinance = _StaticProvider(
        name="yfinance",
        license_note="yahoo license",
        datums={
            "current_price": MarketDatum(90.0, "yfinance", "2026-03-05T00:00:00Z"),
            "shares_outstanding": MarketDatum(
                1_000.0, "yfinance", "2026-03-05T00:00:00Z"
            ),
            "beta": MarketDatum(1.1, "yfinance", "2026-03-05T00:00:00Z"),
            "risk_free_rate": MarketDatum(0.04, "yfinance", "2026-03-05T00:00:00Z"),
            "target_mean_price": MarketDatum(220.0, "yfinance", "2026-03-05T00:00:00Z"),
        },
    )
    tipranks = _StaticProvider(
        name="tipranks",
        license_note="tipranks license",
        datums={
            "target_mean_price": MarketDatum(
                200.0,
                "tipranks",
                "2026-03-05T00:00:00Z",
            ),
            "target_analyst_count": MarketDatum(
                4.0,
                "tipranks",
                "2026-03-05T00:00:00Z",
            ),
        },
    )

    service = MarketDataService(
        ttl_seconds=120,
        max_retries=0,
        providers=(yfinance, tipranks),
    )
    snapshot = service.get_market_snapshot("EXM")

    assert snapshot.target_mean_price == 220.0
    assert snapshot.market_datums["target_mean_price"]["source"] == "yfinance"
    assert snapshot.market_datums["target_mean_price"]["fallback_reason"] == (
        "insufficient_sources"
    )
    assert snapshot.market_datums["target_mean_price"]["horizon"] == "12m"
    quality_flags = snapshot.market_datums["target_mean_price"].get("quality_flags")
    assert isinstance(quality_flags, list)
    assert "consensus_fallback" in quality_flags
    assert snapshot.target_consensus_applied is False
    assert snapshot.target_consensus_fallback_reason == "insufficient_sources"
    assert "insufficient_sources" in snapshot.target_consensus_warning_codes
    assert snapshot.target_consensus_source_count is None
    assert snapshot.target_consensus_quality_bucket == "degraded"
    assert snapshot.target_consensus_confidence_weight == 0.30


def test_market_data_service_classifies_blocked_consensus_fallback_with_governance_warning() -> (
    None
):
    yfinance = _StaticProvider(
        name="yfinance",
        license_note="yahoo license",
        datums={
            "current_price": MarketDatum(90.0, "yfinance", "2026-03-05T00:00:00Z"),
            "shares_outstanding": MarketDatum(
                1_000.0, "yfinance", "2026-03-05T00:00:00Z"
            ),
            "beta": MarketDatum(1.1, "yfinance", "2026-03-05T00:00:00Z"),
            "risk_free_rate": MarketDatum(0.04, "yfinance", "2026-03-05T00:00:00Z"),
            "target_mean_price": MarketDatum(220.0, "yfinance", "2026-03-05T00:00:00Z"),
        },
    )
    blocked_tipranks = _CodedFailingProvider(
        name="tipranks",
        message=(
            "code=provider_blocked_http;url=https://www.tipranks.com/stocks/exm/forecast;"
            "status=403"
        ),
    )

    service = MarketDataService(
        ttl_seconds=120,
        max_retries=0,
        providers=(yfinance, blocked_tipranks),
    )
    snapshot = service.get_market_snapshot("EXM")

    assert snapshot.target_consensus_applied is False
    assert snapshot.target_consensus_fallback_reason == "provider_blocked"
    assert "provider_blocked" in snapshot.target_consensus_warning_codes
    assert "provider_blocked_http" in snapshot.target_consensus_warning_codes
    assert (
        "provider_governance_review_required" in snapshot.target_consensus_warning_codes
    )
    assert snapshot.target_consensus_quality_bucket == "degraded"
    assert snapshot.target_consensus_confidence_weight == 0.30
    assert any(
        "provider_governance_review_required" in warning
        for warning in snapshot.target_consensus_warnings
    )


def test_market_data_service_degrades_single_source_aggregate_consensus(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FUNDAMENTAL_TARGET_CONSENSUS_MIN_SOURCES", "1")
    yfinance = _StaticProvider(
        name="yfinance",
        license_note="yahoo license",
        datums={
            "current_price": MarketDatum(90.0, "yfinance", "2026-03-05T00:00:00Z"),
            "shares_outstanding": MarketDatum(
                1_000.0, "yfinance", "2026-03-05T00:00:00Z"
            ),
            "beta": MarketDatum(1.1, "yfinance", "2026-03-05T00:00:00Z"),
            "risk_free_rate": MarketDatum(0.04, "yfinance", "2026-03-05T00:00:00Z"),
        },
    )
    tipranks = _StaticProvider(
        name="tipranks",
        license_note="tipranks license",
        datums={
            "target_mean_price": MarketDatum(
                200.0,
                "tipranks",
                "2026-03-05T00:00:00Z",
            ),
            "target_analyst_count": MarketDatum(
                24.0,
                "tipranks",
                "2026-03-05T00:00:00Z",
            ),
        },
    )

    service = MarketDataService(
        ttl_seconds=120,
        max_retries=0,
        providers=(yfinance, tipranks),
    )
    snapshot = service.get_market_snapshot("EXM")

    assert snapshot.target_mean_price == 200.0
    assert snapshot.target_consensus_applied is True
    assert snapshot.target_consensus_source_count == 1
    assert snapshot.target_consensus_fallback_reason == "single_source_consensus"
    assert "single_source_consensus" in snapshot.target_consensus_warning_codes
    assert snapshot.target_consensus_quality_bucket == "degraded"
    assert snapshot.target_consensus_confidence_weight == 0.30
    assert any(
        "single_source_consensus" in warning
        for warning in snapshot.target_consensus_warnings
    )
