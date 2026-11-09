from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from test_api import _canonical_fact
from test_postgres_metadata import _snapshot as _make_snapshot

from fundamental_service.annual_history import (
    AnnualHistoryError,
    AnnualHistoryV1,
    resolve_annual_history,
)
from fundamental_service.contracts import (
    CanonicalFactV1,
    IdentityV1,
    PeriodType,
    QualityStatus,
    SourceSnapshotV1,
)

VALUATION_TIME = datetime(2026, 3, 1, tzinfo=UTC)


def _annual_fact(
    field: str,
    year: int,
    value: str,
    *,
    available_at: datetime | None = None,
    fact_id: str | None = None,
    concept: str | None = None,
    amendment: bool = False,
    amendment_scope: str | None = None,
) -> CanonicalFactV1:
    start = datetime(year, 1, 1).date()
    end = datetime(year, 12, 31).date()
    fact = _canonical_fact(fact_id or f"{field}-{year}", field)
    return fact.model_copy(
        update={
            "concept": concept or f"us-gaap:{field}",
            "context": fact.context.model_copy(
                update={
                    "concept_qname": concept or f"us-gaap:{field}",
                    "period_type": PeriodType.DURATION,
                    "start_date": start,
                    "end_date": end,
                    "instant": None,
                }
            ),
            "value": Decimal(value),
            "period_start": start,
            "period_end": end,
            "instant": None,
            "as_of": datetime(year, 12, 31, tzinfo=UTC),
            "available_at": available_at or datetime(year + 1, 2, 1, tzinfo=UTC),
            "filed_at": available_at or datetime(year + 1, 2, 1, tzinfo=UTC),
            "is_amendment": amendment,
            "amendment_scope": amendment_scope,
        }
    )


def _instant_fact(field: str, year: int, value: str) -> CanonicalFactV1:
    end = datetime(year, 12, 31).date()
    fact = _canonical_fact(f"{field}-{year}", field)
    return fact.model_copy(
        update={
            "concept": f"us-gaap:{field}",
            "context": fact.context.model_copy(
                update={
                    "concept_qname": f"us-gaap:{field}",
                    "period_type": PeriodType.INSTANT,
                    "start_date": None,
                    "end_date": None,
                    "instant": end,
                }
            ),
            "value": Decimal(value),
            "period_start": None,
            "period_end": end,
            "instant": end,
            "as_of": datetime(year, 12, 31, tzinfo=UTC),
        }
    )


def _snapshot() -> SourceSnapshotV1:
    return _make_snapshot(
        "annual-history",
        identity=IdentityV1(
            issuer_id="CIK1",
            issuer_name="Example Co",
            domicile="US",
            reporting_basis="us-gaap",
            security_id="COMMON",
            share_class="common",
            currency="USD",
        ),
        valuation_timestamp=VALUATION_TIME,
    )


def _facts(years: range = range(2021, 2026)) -> tuple[CanonicalFactV1, ...]:
    facts = []
    for year in years:
        facts.extend(
            (
                _annual_fact("revenue", year, str(year * 10)),
                _annual_fact("operating_income", year, str(year)),
                _instant_fact("cash", year, "10"),
            )
        )
    return tuple(facts)


def _resolve(facts: Iterable[CanonicalFactV1]) -> AnnualHistoryV1:
    return resolve_annual_history(
        facts,
        snapshot=_snapshot(),
        valuation_timestamp=VALUATION_TIME,
        duration_fields=("revenue", "operating_income"),
        instant_fields=("cash",),
    )


def test_resolves_aligned_duration_and_period_end_instant_facts_as_provisional() -> (
    None
):
    history = _resolve(_facts())

    assert history.requested_fiscal_years == (2025, 2024, 2023, 2022, 2021)
    assert tuple(period.fiscal_year for period in history.periods) == (
        2021,
        2022,
        2023,
        2024,
        2025,
    )
    assert history.periods[-1].fact("revenue").fact_id == "revenue-2025"
    assert history.periods[-1].fact("cash").instant.isoformat() == "2025-12-31"
    assert history.quality is QualityStatus.PROVISIONAL
    assert history.supported_history_threshold is None
    assert history.issue_codes == ("HISTORY_THRESHOLD_UNVALIDATED",)


def test_does_not_use_facts_not_available_at_the_valuation_timestamp() -> None:
    facts = list(_facts())
    facts.append(
        _annual_fact(
            "revenue",
            2025,
            "99999",
            fact_id="future-revenue",
            available_at=datetime(2026, 4, 1, tzinfo=UTC),
        )
    )

    history = _resolve(facts)

    assert history.periods[-1].fact("revenue").value == Decimal(20250)


def test_selects_an_applicable_restatement_only_after_its_available_time() -> None:
    original = _annual_fact("revenue", 2024, "20240", fact_id="revenue-original")
    restated = _annual_fact(
        "revenue",
        2024,
        "19000",
        fact_id="revenue-amended",
        available_at=datetime(2026, 1, 15, tzinfo=UTC),
        amendment=True,
        amendment_scope="valuation_relevant",
    )
    facts = [
        fact
        for fact in _facts()
        if not (fact.normalized_field == "revenue" and fact.period_end.year == 2024)
    ] + [original, restated]
    before = resolve_annual_history(
        facts,
        snapshot=_snapshot(),
        valuation_timestamp=datetime(2026, 1, 3, tzinfo=UTC),
        duration_fields=("revenue", "operating_income"),
        instant_fields=("cash",),
    )
    after = _resolve(facts)

    assert before.periods[-1].fact("revenue").fact_id == "revenue-original"
    assert after.periods[-2].fact("revenue").fact_id == "revenue-amended"


def test_same_period_mapping_conflict_abstains_instead_of_sorting_a_winner() -> None:
    conflict = _annual_fact(
        "revenue",
        2025,
        "20250",
        fact_id="revenue-other-concept",
        concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )

    with pytest.raises(AnnualHistoryError) as error:
        _resolve((*_facts(), conflict))

    assert error.value.code == "HISTORY_MAPPING_CONFLICT"


def test_missing_period_components_are_reported_and_do_not_create_a_history_floor() -> (
    None
):
    facts = tuple(
        fact
        for fact in _facts(range(2021, 2026))
        if not (
            fact.normalized_field == "operating_income" and fact.period_end.year == 2024
        )
    )

    history = _resolve(facts)

    assert history.quality is QualityStatus.ABSTAIN
    assert (2024, "operating_income") in history.missing_fields
    assert tuple(period.fiscal_year for period in history.periods) == (2025,)
    assert history.issue_codes == ("HISTORY_MINIMUM_PERIODS_UNAVAILABLE",)
