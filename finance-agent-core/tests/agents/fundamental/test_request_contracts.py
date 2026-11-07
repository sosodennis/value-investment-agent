from datetime import UTC, datetime

import pytest

from src.agents.fundamental.interface.request_contracts import (
    ExplicitFiscalPeriodSelectorV1,
    FundamentalRequestTimingV1,
    LatestCompleteFiscalPeriodSelectorV1,
    apply_request_timing,
)


def test_missing_time_is_created_once_and_defaults_to_three_periods() -> None:
    accepted_at = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    timing = FundamentalRequestTimingV1.accept(
        {"valuation_context": {}}, clock=lambda: accepted_at
    )

    assert timing.valuation_timestamp == accepted_at
    assert timing.timestamp_source == "accepted_at"
    assert isinstance(
        timing.fiscal_period_selector, LatestCompleteFiscalPeriodSelectorV1
    )
    assert timing.fiscal_period_selector.count == 3


def test_historical_requested_as_of_is_preserved_as_utc() -> None:
    requested = datetime.fromisoformat("2024-12-31T23:00:00-05:00")
    timing = FundamentalRequestTimingV1.accept({"requested_as_of": requested})

    assert timing.valuation_timestamp == datetime(2025, 1, 1, 4, 0, tzinfo=UTC)
    assert timing.requested_as_of == timing.valuation_timestamp
    assert timing.timestamp_source == "caller_requested_as_of"


def test_explicit_periods_are_versioned_and_unique() -> None:
    timing = FundamentalRequestTimingV1.accept(
        {
            "requested_as_of": datetime(2026, 1, 1, tzinfo=UTC),
            "fiscal_period_selector": {
                "mode": "explicit_periods",
                "periods": [{"fiscal_year": 2024}, {"fiscal_year": 2025}],
            },
        }
    )

    assert isinstance(timing.fiscal_period_selector, ExplicitFiscalPeriodSelectorV1)
    assert timing.fiscal_period_selector.version == (
        "fundamental.fiscal-period-selector.v1"
    )
    assert tuple(
        period.fiscal_year for period in timing.fiscal_period_selector.periods
    ) == (2024, 2025)

    with pytest.raises(ValueError, match="unique"):
        FundamentalRequestTimingV1.accept(
            {
                "fiscal_period_selector": {
                    "mode": "explicit_periods",
                    "periods": [{"fiscal_year": 2024}, {"fiscal_year": 2024}],
                }
            }
        )


def test_naive_timestamp_and_conflicting_canonical_time_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        FundamentalRequestTimingV1.accept({"requested_as_of": datetime(2026, 1, 1)})
    with pytest.raises(ValueError, match="must match"):
        FundamentalRequestTimingV1.accept(
            {
                "requested_as_of": datetime(2026, 1, 1, tzinfo=UTC),
                "valuation_context": {
                    "valuation_timestamp": datetime(2026, 1, 2, tzinfo=UTC)
                },
            }
        )


def test_apply_request_timing_removes_external_only_fields() -> None:
    timing = FundamentalRequestTimingV1.accept(
        {"requested_as_of": datetime(2026, 1, 1, tzinfo=UTC)}
    )
    payload = apply_request_timing(
        {
            "requested_as_of": datetime(2026, 1, 1, tzinfo=UTC),
            "fiscal_period_selector": {"mode": "latest_complete", "count": 5},
            "valuation_context": {"source_selection_policy": "pit-v1"},
        },
        timing,
    )

    assert "requested_as_of" not in payload
    assert "fiscal_period_selector" not in payload
    assert payload["valuation_context"]["valuation_timestamp"] == (
        "2026-01-01T00:00:00+00:00"
    )
    assert payload["valuation_context"]["fiscal_period_selector"]["count"] == 3


def test_apply_request_timing_builds_cold_start_snapshot_selector() -> None:
    timing = FundamentalRequestTimingV1.accept(
        {"requested_as_of": datetime(2026, 1, 1, tzinfo=UTC)}
    )
    payload = apply_request_timing(
        {
            "requested_as_of": datetime(2026, 1, 1, tzinfo=UTC),
            "required_fields": ["revenue", "operating_income"],
            "identity": {"issuer_id": "0000789019", "security_id": "MSFT"},
            "valuation_context": {
                "source_selection_policy": "pit-v1",
                "coverage_profile": "us-gaap-public-v1",
            },
        },
        timing,
    )

    assert "required_fields" not in payload
    assert payload["snapshot_selector"]["required_fields"] == [
        "revenue",
        "operating_income",
    ]
    assert payload["snapshot_selector"]["fiscal_period_selector"]["count"] == 3
