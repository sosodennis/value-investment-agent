from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fundamental_service.forecast_timeline import (
    ForecastTimelineError,
    build_forecast_timeline,
    verify_forecast_timeline_sources,
)
from fundamental_service.forecast_timeline_contracts import ForecastTimelineV1
from pydantic import ValidationError
from test_valuation_preparation import _fact


def revenue_history(month=6, day=30):
    facts = []
    for year in (2024, 2025, 2026):
        end = date(year, month, day)
        start = date(year - 1, month, day) + timedelta(days=1)
        fact = _fact(
            "revenue",
            year,
            str(year),
            available_at=datetime(year, month, day, tzinfo=UTC),
        )
        facts.append(
            fact.model_copy(
                update={
                    "period_start": start,
                    "period_end": end,
                    "context": fact.context.model_copy(
                        update={"start_date": start, "end_date": end}
                    ),
                }
            )
        )
    return tuple(facts)


def test_june_year_end_keeps_annual_and_included_coverage_distinct():
    facts = revenue_history()
    timeline = build_forecast_timeline(
        facts, valuation_timestamp=datetime(2026, 11, 23, tzinfo=UTC), horizon=5
    )
    first = timeline.periods[0]
    assert (first.period_start, first.period_end) == (
        date(2026, 7, 1),
        date(2027, 6, 30),
    )
    assert first.included_start == date(2026, 11, 24)
    assert first.included_days == first.discount_days == 219
    assert first.full_period_days == 365
    assert (
        timeline.periods[1].included_days == timeline.periods[1].full_period_days == 366
    )
    assert [period.period_end.year for period in timeline.periods] == list(
        range(2027, 2032)
    )
    verify_forecast_timeline_sources(
        timeline,
        facts,
        valuation_timestamp=datetime(2026, 11, 23, tzinfo=UTC),
        horizon=5,
        base_revenue=Decimal(2026),
    )


def test_utc_end_of_day_and_one_remaining_day():
    timestamp = datetime(2027, 6, 30, 7, tzinfo=timezone(timedelta(hours=8)))
    timeline = build_forecast_timeline(
        revenue_history(), valuation_timestamp=timestamp, horizon=1
    )
    assert timeline.valuation_date == date(2027, 6, 29)
    assert timeline.periods[0].included_days == timeline.periods[0].discount_days == 1
    with pytest.raises(ForecastTimelineError) as error:
        build_forecast_timeline(
            revenue_history(),
            valuation_timestamp=datetime(2027, 6, 30, tzinfo=UTC),
            horizon=1,
        )
    assert error.value.code == "FORECAST_BASE_PERIOD_STALE"


def test_anchor_end_includes_a_full_year_and_february_month_end_leaps():
    facts = []
    previous = date(2023, 2, 28)
    for year, day in ((2024, 29), (2025, 28), (2026, 28)):
        fact = revenue_history()[year - 2024]
        start, end = previous + timedelta(days=1), date(year, 2, day)
        facts.append(
            fact.model_copy(
                update={
                    "period_start": start,
                    "period_end": end,
                    "available_at": datetime(year, 3, 1, tzinfo=UTC),
                    "context": fact.context.model_copy(
                        update={"start_date": start, "end_date": end}
                    ),
                }
            )
        )
        previous = end
    timeline = build_forecast_timeline(
        facts, valuation_timestamp=datetime(2026, 3, 1, tzinfo=UTC), horizon=3
    )
    assert timeline.calendar_basis == "source-month-end"
    assert [period.period_end for period in timeline.periods] == [
        date(2027, 2, 28),
        date(2028, 2, 29),
        date(2029, 2, 28),
    ]
    full = build_forecast_timeline(
        revenue_history(),
        valuation_timestamp=datetime(2026, 6, 30, tzinfo=UTC),
        horizon=1,
    )
    assert full.periods[0].included_days == full.periods[0].full_period_days


@pytest.mark.parametrize("change", ["weekly", "future_available", "gap", "duplicate"])
def test_unsupported_or_unavailable_calendar_is_explicit(change):
    facts = list(revenue_history())
    fact = facts[-1]
    if change == "weekly":
        facts[-1] = fact.model_copy(
            update={"period_end": fact.period_end - timedelta(days=2)}
        )
    elif change == "future_available":
        facts[-1] = fact.model_copy(
            update={"available_at": datetime(2027, 1, 1, tzinfo=UTC)}
        )
    elif change == "gap":
        facts[-1] = fact.model_copy(
            update={"period_start": fact.period_start + timedelta(days=1)}
        )
    else:
        facts.append(fact)
    with pytest.raises(ForecastTimelineError) as error:
        build_forecast_timeline(
            facts, valuation_timestamp=datetime(2026, 11, 23, tzinfo=UTC), horizon=5
        )
    assert error.value.code == "FORECAST_CALENDAR_UNRESOLVED"


def test_tampered_counts_and_retained_anchor_cannot_be_accepted():
    facts = revenue_history()
    timestamp = datetime(2026, 11, 23, tzinfo=UTC)
    timeline = build_forecast_timeline(facts, valuation_timestamp=timestamp, horizon=5)
    raw = timeline.model_dump(mode="json")
    raw["periods"][0]["discount_days"] += 1
    with pytest.raises(ValidationError, match="discount days"):
        ForecastTimelineV1.model_validate(raw)
    forged = timeline.model_copy(update={"source_period_start": date(2025, 6, 30)})
    with pytest.raises(ForecastTimelineError, match="retained annual"):
        verify_forecast_timeline_sources(
            forged,
            facts,
            valuation_timestamp=timestamp,
            horizon=5,
            base_revenue=Decimal(2026),
        )
    with pytest.raises(ForecastTimelineError, match="revenue must equal"):
        verify_forecast_timeline_sources(
            timeline,
            facts,
            valuation_timestamp=timestamp,
            horizon=5,
            base_revenue=Decimal(2027),
        )
