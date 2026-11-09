"""Resolve aligned, point-in-time annual facts for valuation preparation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .contracts import (
    CanonicalFactV1,
    QualityStatus,
    SourceSnapshotV1,
)

_MIN_ANNUAL_DAYS = 300
_MAX_ANNUAL_DAYS = 380
_CANDIDATE_WINDOW_YEARS = 5
_CANDIDATE_MINIMUM_YEARS = 3


class AnnualHistoryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AnnualHistoryPeriodV1:
    fiscal_year: int
    period_start: date
    period_end: date
    duration_facts: tuple[CanonicalFactV1, ...]
    instant_facts: tuple[CanonicalFactV1, ...]

    def fact(self, normalized_field: str) -> CanonicalFactV1 | None:
        return next(
            (
                item
                for item in (*self.duration_facts, *self.instant_facts)
                if item.normalized_field == normalized_field
            ),
            None,
        )


@dataclass(frozen=True)
class AnnualHistoryV1:
    requested_fiscal_years: tuple[int, ...]
    periods: tuple[AnnualHistoryPeriodV1, ...]
    missing_fields: tuple[tuple[int, str], ...]
    quality: QualityStatus
    issue_codes: tuple[str, ...]
    supported_history_threshold: int | None = None


def resolve_annual_history(
    facts: Iterable[CanonicalFactV1],
    *,
    snapshot: SourceSnapshotV1,
    valuation_timestamp: datetime,
    duration_fields: tuple[str, ...],
    instant_fields: tuple[str, ...],
    anchor_field: str = "revenue",
) -> AnnualHistoryV1:
    """Resolve the latest five annual periods without choosing conflicting facts.

    The three-of-five threshold is a candidate only. Until a supported threshold
    is explicitly promoted, a usable history remains provisional.
    """

    if not duration_fields or anchor_field not in duration_fields:
        raise ValueError("anchor_field must be one of the duration fields")
    if len(set(duration_fields + instant_fields)) != len(duration_fields) + len(
        instant_fields
    ):
        raise ValueError("history fields must be unique")
    if valuation_timestamp.tzinfo is None or valuation_timestamp.utcoffset() is None:
        raise ValueError("valuation_timestamp must include a timezone")

    source_records = {record.content_hash: record for record in snapshot.source_records}
    requested_fields = set(duration_fields + instant_fields)
    eligible = tuple(
        fact
        for fact in facts
        if fact.normalized_field in requested_fields
        and fact.issuer_id == snapshot.identity.issuer_id
        and fact.security_id in {None, snapshot.identity.security_id}
        and fact.source.content_hash in source_records
        and fact.available_at <= valuation_timestamp
        and source_records[fact.source.content_hash].available_at <= valuation_timestamp
        and fact.quality is QualityStatus.VERIFIED
        and not fact.context.dimensions
        and fact.context.consolidation_scope == "consolidated"
        and fact.currency in {None, snapshot.identity.currency}
        and isinstance(fact.value, Decimal)
    )

    duration_by_year: dict[int, dict[str, CanonicalFactV1]] = {}
    anchor_years: set[int] = set()
    for field in duration_fields:
        field_facts = tuple(
            fact
            for fact in eligible
            if fact.normalized_field == field
            and fact.context.period_type.value == "duration"
            and fact.period_start is not None
            and fact.period_end <= valuation_timestamp.date()
            and _MIN_ANNUAL_DAYS
            <= (fact.period_end - fact.period_start).days
            <= _MAX_ANNUAL_DAYS
        )
        by_year: dict[int, list[CanonicalFactV1]] = {}
        for fact in field_facts:
            by_year.setdefault(fact.period_end.year, []).append(fact)
        for fiscal_year, candidates in by_year.items():
            selected = _select_period_fact(
                candidates,
                fiscal_year=fiscal_year,
                field=field,
                expected_instant=None,
            )
            if selected is None:
                continue
            duration_by_year.setdefault(fiscal_year, {})[field] = selected
            if field == anchor_field:
                anchor_years.add(fiscal_year)

    latest_year = max(anchor_years, default=valuation_timestamp.year)
    requested_years = tuple(
        range(latest_year, latest_year - _CANDIDATE_WINDOW_YEARS, -1)
    )

    missing_fields: list[tuple[int, str]] = []
    complete_by_year: dict[int, AnnualHistoryPeriodV1] = {}
    for fiscal_year in requested_years:
        selected_duration = duration_by_year.get(fiscal_year, {})
        missing_fields.extend(
            (fiscal_year, field)
            for field in duration_fields
            if field not in selected_duration
        )
        if not selected_duration:
            continue

        period_shapes = {
            (fact.period_start, fact.period_end) for fact in selected_duration.values()
        }
        if len(period_shapes) > 1:
            raise AnnualHistoryError(
                "HISTORY_PERIOD_ALIGNMENT_CONFLICT",
                f"duration facts do not align to one fiscal period in {fiscal_year}",
            )
        period_start, period_end = next(iter(period_shapes))
        selected_instant: dict[str, CanonicalFactV1] = {}
        for field in instant_fields:
            candidates = tuple(
                fact
                for fact in eligible
                if fact.normalized_field == field
                and fact.context.period_type.value == "instant"
                and fact.instant == period_end
            )
            selected = _select_period_fact(
                candidates,
                fiscal_year=fiscal_year,
                field=field,
                expected_instant=period_end,
            )
            if selected is None:
                missing_fields.append((fiscal_year, field))
            else:
                selected_instant[field] = selected

        if len(selected_duration) != len(duration_fields) or len(
            selected_instant
        ) != len(instant_fields):
            continue
        period = AnnualHistoryPeriodV1(
            fiscal_year=fiscal_year,
            period_start=period_start,
            period_end=period_end,
            duration_facts=tuple(selected_duration[field] for field in duration_fields),
            instant_facts=tuple(selected_instant[field] for field in instant_fields),
        )
        complete_by_year[fiscal_year] = period

    trailing_years: list[int] = []
    for fiscal_year in requested_years:
        if fiscal_year not in complete_by_year:
            break
        trailing_years.append(fiscal_year)

    trailing_periods = tuple(
        complete_by_year[year] for year in reversed(trailing_years)
    )
    if len(trailing_years) < _CANDIDATE_MINIMUM_YEARS:
        return AnnualHistoryV1(
            requested_fiscal_years=requested_years,
            periods=trailing_periods,
            missing_fields=tuple(sorted(set(missing_fields))),
            quality=QualityStatus.ABSTAIN,
            issue_codes=("HISTORY_MINIMUM_PERIODS_UNAVAILABLE",),
        )

    issue_codes = ["HISTORY_THRESHOLD_UNVALIDATED"]
    if missing_fields:
        issue_codes.append("HISTORY_WINDOW_PARTIALLY_UNAVAILABLE")
    return AnnualHistoryV1(
        requested_fiscal_years=requested_years,
        periods=trailing_periods,
        missing_fields=tuple(sorted(set(missing_fields))),
        quality=QualityStatus.PROVISIONAL,
        issue_codes=tuple(issue_codes),
    )


def _select_period_fact(
    candidates: tuple[CanonicalFactV1, ...],
    *,
    fiscal_year: int,
    field: str,
    expected_instant: date | None,
) -> CanonicalFactV1 | None:
    if not candidates:
        return None
    period_shapes = {
        (fact.period_start, fact.period_end)
        if expected_instant is None
        else (fact.instant,)
        for fact in candidates
    }
    if len(period_shapes) != 1:
        raise AnnualHistoryError(
            "HISTORY_PERIOD_ALIGNMENT_CONFLICT",
            f"multiple period shapes are available for {field} in {fiscal_year}",
        )
    concepts = {fact.concept for fact in candidates}
    if len(concepts) != 1:
        raise AnnualHistoryError(
            "HISTORY_MAPPING_CONFLICT",
            f"multiple concepts map to {field} in {fiscal_year}",
        )
    if any(
        fact.is_amendment and fact.amendment_scope in {None, "unknown"}
        for fact in candidates
    ):
        raise AnnualHistoryError(
            "FACT_AMENDMENT_SCOPE_UNKNOWN",
            f"amendment scope is unresolved for {field} in {fiscal_year}",
        )
    applicable = tuple(
        fact
        for fact in candidates
        if not (fact.is_amendment and fact.amendment_scope == "unrelated")
    )
    if not applicable:
        return None
    latest_available = max(fact.available_at for fact in applicable)
    latest = tuple(fact for fact in applicable if fact.available_at == latest_available)
    values = {
        (
            fact.value,
            fact.unit,
            fact.scale,
            fact.currency,
            fact.mapping_decision_id,
        )
        for fact in latest
    }
    if len(values) != 1:
        raise AnnualHistoryError(
            "HISTORY_FACT_CONFLICT",
            f"equally available facts disagree for {field} in {fiscal_year}",
        )
    return min(latest, key=lambda fact: fact.fact_id)


__all__ = [
    "AnnualHistoryError",
    "AnnualHistoryPeriodV1",
    "AnnualHistoryV1",
    "resolve_annual_history",
]
