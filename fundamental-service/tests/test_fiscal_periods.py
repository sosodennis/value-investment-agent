from datetime import UTC, datetime

from fundamental_service.contracts import (
    FiscalPeriodSelectorV1,
    FiscalPeriodV1,
    IdentityV1,
)
from fundamental_service.fiscal_periods import resolve_fiscal_periods
from test_api import _canonical_fact
from test_postgres_metadata import _snapshot


def _identity() -> IdentityV1:
    return IdentityV1(
        issuer_id="CIK1",
        issuer_name="Microsoft Corporation",
        domicile="US",
        reporting_basis="us-gaap",
        security_id="COMMON",
        share_class="common",
        currency="USD",
    )


def _fact(year: int, *, fiscal_year_end_month: int = 12):
    end = datetime(
        year, fiscal_year_end_month, 30 if fiscal_year_end_month == 9 else 31
    ).date()
    start = datetime(
        year - (1 if fiscal_year_end_month == 9 else 0),
        10 if fiscal_year_end_month == 9 else 1,
        1,
    ).date()
    fact = _canonical_fact(f"fact-revenue-{year}", "revenue")
    return fact.model_copy(
        update={
            "period_start": start,
            "period_end": end,
            "as_of": datetime(year, fiscal_year_end_month, 30, tzinfo=UTC),
            "available_at": datetime(year + 1, 1, 15, tzinfo=UTC),
        }
    )


def test_msft_default_resolves_three_complete_periods_at_year_boundary():
    snapshot = _snapshot(
        "msft-fiscal",
        identity=_identity(),
        valuation_timestamp=datetime(2026, 2, 1, tzinfo=UTC),
    )
    selection = resolve_fiscal_periods(
        (_fact(2023), _fact(2024), _fact(2025)),
        snapshot=snapshot,
        valuation_timestamp=datetime(2026, 2, 1, tzinfo=UTC),
        selector=FiscalPeriodSelectorV1(mode="latest_complete", count=3),
        required_fields=("revenue",),
    )

    assert selection.resolution.status == "resolved"
    assert selection.resolution.requested_fiscal_years == (2025, 2024, 2023)
    assert tuple(
        period.fiscal_year for period in selection.resolution.resolved_periods
    ) == (
        2025,
        2024,
        2023,
    )


def test_unavailable_current_period_is_explicit_at_year_boundary():
    snapshot = _snapshot(
        "msft-boundary",
        identity=_identity(),
        valuation_timestamp=datetime(2025, 9, 29, tzinfo=UTC),
    )
    selection = resolve_fiscal_periods(
        (_fact(2023), _fact(2024), _fact(2025)),
        snapshot=snapshot,
        valuation_timestamp=datetime(2025, 9, 29, tzinfo=UTC),
        selector=FiscalPeriodSelectorV1(
            mode="explicit_periods", periods=(FiscalPeriodV1(fiscal_year=2025),)
        ),
        required_fields=("revenue",),
    )

    assert selection.resolution.status == "unavailable"
    assert selection.resolution.missing_fiscal_years == (2025,)
    assert selection.resolution.issue_codes == ("FISCAL_PERIODS_UNAVAILABLE",)


def test_latest_complete_reports_a_gap_in_the_requested_window():
    snapshot = _snapshot(
        "msft-gap",
        identity=_identity(),
        valuation_timestamp=datetime(2026, 2, 1, tzinfo=UTC),
    )
    selection = resolve_fiscal_periods(
        (_fact(2023), _fact(2025)),
        snapshot=snapshot,
        valuation_timestamp=datetime(2026, 2, 1, tzinfo=UTC),
        selector=FiscalPeriodSelectorV1(mode="latest_complete", count=3),
        required_fields=("revenue",),
    )

    assert selection.resolution.status == "degraded"
    assert selection.resolution.requested_fiscal_years == (2025, 2024, 2023)
    assert selection.resolution.missing_fiscal_years == (2024,)


def test_non_calendar_fiscal_year_uses_issuer_period_end_metadata():
    snapshot = _snapshot(
        "non-calendar",
        identity=_identity(),
        valuation_timestamp=datetime(2026, 2, 1, tzinfo=UTC),
    )
    selection = resolve_fiscal_periods(
        (
            _fact(2023, fiscal_year_end_month=9),
            _fact(2024, fiscal_year_end_month=9),
            _fact(2025, fiscal_year_end_month=9),
        ),
        snapshot=snapshot,
        valuation_timestamp=datetime(2026, 2, 1, tzinfo=UTC),
        selector=FiscalPeriodSelectorV1(mode="latest_complete", count=3),
        required_fields=("revenue",),
    )

    assert selection.resolution.status == "resolved"
    assert selection.resolution.resolved_periods[-1].period_start.month == 10
    assert selection.resolution.resolved_periods[-1].period_end.month == 9
