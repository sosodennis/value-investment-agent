"""Point-in-time fiscal-period resolution for the Fundamental service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .contracts import (
    CanonicalFactV1,
    FiscalPeriodResolutionV1,
    FiscalPeriodSelectorV1,
    QualityStatus,
    ResolvedFiscalPeriodV1,
    SourceSnapshotV1,
)


@dataclass(frozen=True)
class FiscalPeriodSelection:
    facts: tuple[CanonicalFactV1, ...]
    resolution: FiscalPeriodResolutionV1


def resolve_fiscal_periods(
    facts: Iterable[CanonicalFactV1],
    *,
    snapshot: SourceSnapshotV1,
    valuation_timestamp: datetime,
    selector: FiscalPeriodSelectorV1,
    required_fields: tuple[str, ...],
) -> FiscalPeriodSelection:
    """Resolve complete annual issuer periods without substituting other years."""

    source_hashes = {record.content_hash for record in snapshot.source_records}
    candidates = [
        fact
        for fact in facts
        if (
            fact.issuer_id == snapshot.identity.issuer_id
            and fact.security_id in {None, snapshot.identity.security_id}
            and fact.quality is QualityStatus.VERIFIED
            and fact.available_at <= valuation_timestamp
            and fact.period_start is not None
            and fact.period_end <= valuation_timestamp.date()
            and fact.source.content_hash in source_hashes
            and (fact.period_end - fact.period_start).days >= 300
            and fact.normalized_field in required_fields
        )
    ]
    by_year: dict[int, dict[str, CanonicalFactV1]] = {}
    for fact in candidates:
        fiscal_year = fact.period_end.year
        fields = by_year.setdefault(fiscal_year, {})
        current = fields.get(fact.normalized_field)
        if current is None or (
            fact.period_end,
            fact.available_at,
            fact.fact_id,
        ) > (
            current.period_end,
            current.available_at,
            current.fact_id,
        ):
            fields[fact.normalized_field] = fact

    available_years = sorted(
        year
        for year, field_facts in by_year.items()
        if set(required_fields).issubset(field_facts)
    )
    if selector.mode == "latest_complete":
        assert selector.count is not None
        latest_year = (
            max(available_years) if available_years else valuation_timestamp.year
        )
        requested_years = tuple(range(latest_year, latest_year - selector.count, -1))
        missing_years = tuple(
            year for year in requested_years if year not in available_years
        )
    else:
        requested_years = tuple(period.fiscal_year for period in selector.periods)
        missing_years = tuple(
            year for year in requested_years if year not in available_years
        )

    resolved_periods = tuple(
        _period_metadata(year, by_year[year].values())
        for year in requested_years
        if year in by_year and year not in missing_years
    )
    selected_facts = tuple(
        fact
        for year in requested_years
        if year in by_year and year not in missing_years
        for fact in sorted(by_year[year].values(), key=lambda item: item.fact_id)
    )
    if not missing_years:
        status = "resolved"
        issue_codes: tuple[str, ...] = ()
    elif resolved_periods:
        status = "degraded"
        issue_codes = ("FISCAL_PERIODS_PARTIALLY_UNAVAILABLE",)
    else:
        status = "unavailable"
        issue_codes = ("FISCAL_PERIODS_UNAVAILABLE",)
    resolution = FiscalPeriodResolutionV1(
        status=status,
        selector=selector,
        requested_fiscal_years=requested_years,
        resolved_periods=resolved_periods,
        missing_fiscal_years=missing_years,
        issue_codes=issue_codes,
    )
    return FiscalPeriodSelection(facts=selected_facts, resolution=resolution)


def _period_metadata(
    fiscal_year: int, facts: Iterable[CanonicalFactV1]
) -> ResolvedFiscalPeriodV1:
    period_facts = tuple(facts)
    return ResolvedFiscalPeriodV1(
        fiscal_year=fiscal_year,
        period_start=min(
            fact.period_start for fact in period_facts if fact.period_start
        ),
        period_end=max(fact.period_end for fact in period_facts),
        available_at=max(fact.available_at for fact in period_facts),
    )


__all__ = ["FiscalPeriodSelection", "resolve_fiscal_periods"]
