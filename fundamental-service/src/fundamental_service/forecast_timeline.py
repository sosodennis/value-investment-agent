import calendar
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from .contracts import CanonicalFactV1
from .forecast_timeline_contracts import (
    DATED_FCFF_POLICY,
    ForecastPeriodV1,
    ForecastTimelineV1,
)


class ForecastTimelineError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _year_end(anchor: date, year: int, *, month_end: bool) -> date:
    day = calendar.monthrange(year, anchor.month)[1] if month_end else anchor.day
    try:
        return date(year, anchor.month, day)
    except ValueError as error:
        raise ForecastTimelineError(
            "FORECAST_CALENDAR_UNRESOLVED",
            "fixed-day calendar cannot project this year",
        ) from error


def build_forecast_timeline(
    revenue_facts: Iterable[CanonicalFactV1],
    *,
    valuation_timestamp: datetime,
    horizon: int,
) -> ForecastTimelineV1:
    if valuation_timestamp.tzinfo is None or valuation_timestamp.utcoffset() is None:
        raise ValueError("valuation timestamp must include a timezone")
    valuation_date = valuation_timestamp.astimezone(UTC).date()
    facts = tuple(
        sorted(
            (fact for fact in revenue_facts if fact.normalized_field == "revenue"),
            key=lambda fact: fact.period_end,
        )
    )
    if len(facts) < 3:
        raise ForecastTimelineError(
            "FORECAST_CALENDAR_UNRESOLVED",
            "three comparable annual revenue periods are required",
        )
    facts = facts[-3:]
    anchor = facts[-1]
    month_end = all(
        fact.period_end.day
        == calendar.monthrange(fact.period_end.year, fact.period_end.month)[1]
        for fact in facts
    )
    for index, fact in enumerate(facts):
        if (
            fact.period_start is None
            or fact.available_at > valuation_timestamp
            or fact.period_end > valuation_date
            or fact.context.period_type.value != "duration"
            or (fact.period_end - fact.period_start).days + 1 not in {365, 366}
            or fact.period_end.month != anchor.period_end.month
            or (not month_end and fact.period_end.day != anchor.period_end.day)
            or fact.issuer_id != anchor.issuer_id
            or fact.unit != anchor.unit
            or fact.currency != anchor.currency
            or fact.context.start_date != fact.period_start
            or fact.context.end_date != fact.period_end
            or fact.context.consolidation_scope != "consolidated"
            or fact.context.entity_scope != anchor.context.entity_scope
            or fact.context.dimensions != anchor.context.dimensions
            or (
                index
                and fact.period_start != facts[index - 1].period_end + timedelta(days=1)
            )
            or fact.period_end
            != _year_end(
                anchor.period_end,
                anchor.period_end.year - 2 + index,
                month_end=month_end,
            )
        ):
            raise ForecastTimelineError(
                "FORECAST_CALENDAR_UNRESOLVED",
                "annual revenue evidence does not establish a stable comparable calendar",
            )
    first_end = _year_end(
        anchor.period_end, anchor.period_end.year + 1, month_end=month_end
    )
    if valuation_date >= first_end:
        raise ForecastTimelineError(
            "FORECAST_BASE_PERIOD_STALE",
            "the first forecast year has ended; refresh the annual revenue anchor",
        )
    if horizon not in range(1, 11):
        raise ForecastTimelineError(
            "FORECAST_HORIZON_INVALID", "dated FCFF supports one to ten annual periods"
        )
    periods = []
    previous_end = anchor.period_end
    for ordinal in range(1, horizon + 1):
        period_start = previous_end + timedelta(days=1)
        period_end = _year_end(
            anchor.period_end, anchor.period_end.year + ordinal, month_end=month_end
        )
        included_start = max(period_start, valuation_date + timedelta(days=1))
        periods.append(
            ForecastPeriodV1(
                ordinal=ordinal,
                period_start=period_start,
                period_end=period_end,
                included_start=included_start,
                cash_flow_date=period_end,
                full_period_days=(period_end - period_start).days + 1,
                included_days=(period_end - included_start).days + 1,
                discount_days=(period_end - valuation_date).days,
            )
        )
        previous_end = period_end
    assert anchor.period_start is not None
    return ForecastTimelineV1(
        policy_version=DATED_FCFF_POLICY,
        calendar_basis="source-month-end" if month_end else "source-fixed-month-day",
        valuation_date=valuation_date,
        source_period_start=anchor.period_start,
        source_period_end=anchor.period_end,
        source_revenue_fact_id=anchor.fact_id,
        calendar_fact_ids=tuple(fact.fact_id for fact in facts),
        periods=tuple(periods),
    )


def verify_forecast_timeline_sources(
    timeline: ForecastTimelineV1,
    facts: Iterable[CanonicalFactV1],
    *,
    valuation_timestamp: datetime,
    horizon: int,
    base_revenue: Decimal | None,
) -> None:
    facts = tuple(facts)
    expected = build_forecast_timeline(
        facts, valuation_timestamp=valuation_timestamp, horizon=horizon
    )
    if timeline != expected:
        raise ForecastTimelineError(
            "FORECAST_TIMELINE_SOURCE_MISMATCH",
            "dated schedule does not match retained annual revenue evidence",
        )
    anchor = next(
        fact for fact in facts if fact.fact_id == timeline.source_revenue_fact_id
    )
    if anchor.value != base_revenue:
        raise ForecastTimelineError(
            "FORECAST_BASE_REVENUE_MISMATCH",
            "dated forecast revenue must equal its retained source anchor",
        )
