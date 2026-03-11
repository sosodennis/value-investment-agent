from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median

from .market_datum import MarketDatum

DEFAULT_TARGET_CONSENSUS_MAX_AGE_DAYS = 90
DEFAULT_TARGET_CONSENSUS_MIN_ANALYST_COUNT = 8
DEFAULT_TARGET_CONSENSUS_MIN_SOURCES = 2

FREE_CONSENSUS_AGGREGATE_SOURCE = "free_consensus_aggregate"
FREE_CONSENSUS_PROVIDER_ORDER: tuple[str, ...] = (
    "tipranks",
    "investing",
    "marketbeat",
    "yfinance",
)


@dataclass(frozen=True)
class ConsensusAnchorAggregateResult:
    datums: dict[str, MarketDatum]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class _ConsensusCandidate:
    source: str
    target_mean: float
    target_high: float | None
    target_low: float | None
    analyst_count: int | None
    as_of: str | None


def build_target_consensus_anchor_datums(
    *,
    provider_results: dict[str, dict[str, MarketDatum]],
    now: datetime | None = None,
) -> ConsensusAnchorAggregateResult:
    ts = now or datetime.now(timezone.utc)
    max_age_days = _target_consensus_max_age_days()
    min_analyst_count = _target_consensus_min_analyst_count()
    min_sources = _target_consensus_min_sources()
    warnings: list[str] = []
    candidates: list[_ConsensusCandidate] = []

    for source in FREE_CONSENSUS_PROVIDER_ORDER:
        datums = provider_results.get(source)
        if not datums:
            continue
        target_datum = datums.get("target_mean_price")
        if target_datum is None or target_datum.value is None:
            continue

        age_days = _staleness_days(target_datum.as_of, now=ts)
        if age_days is not None and age_days > max_age_days:
            warnings.append(
                f"{source} target_mean_price stale: age_days={age_days}, "
                f"max_days={max_age_days}"
            )
            continue

        analyst_count = _to_analyst_count(datums.get("target_analyst_count"))
        if (
            source != "yfinance"
            and analyst_count is not None
            and analyst_count < min_analyst_count
        ):
            warnings.append(
                f"{source} target_mean_price filtered by analyst_count="
                f"{analyst_count} (<{min_analyst_count})"
            )
            continue

        candidates.append(
            _ConsensusCandidate(
                source=source,
                target_mean=target_datum.value,
                target_high=_to_float(datums.get("target_high_price")),
                target_low=_to_float(datums.get("target_low_price")),
                analyst_count=analyst_count,
                as_of=target_datum.as_of,
            )
        )

    if len(candidates) < min_sources:
        warnings.append(
            f"target consensus aggregate skipped: insufficient_sources="
            f"{len(candidates)} (<{min_sources})"
        )
        return ConsensusAnchorAggregateResult(datums={}, warnings=tuple(warnings))

    target_median = float(median(item.target_mean for item in candidates))
    highs = [item.target_high for item in candidates if item.target_high is not None]
    lows = [item.target_low for item in candidates if item.target_low is not None]
    analyst_counts = [
        item.analyst_count for item in candidates if item.analyst_count is not None
    ]
    analyst_total = sum(analyst_counts) if analyst_counts else 0
    sources = ",".join(item.source for item in candidates)

    quality_flags: list[str] = ["aggregated", "consensus_anchor"]
    if any(item.analyst_count is None for item in candidates):
        quality_flags.append("coverage_unknown")
    if analyst_total and analyst_total < min_analyst_count * len(candidates):
        quality_flags.append("coverage_low")

    as_of = _latest_as_of(item.as_of for item in candidates) or ts.isoformat()
    source_detail = (
        f"method=cross_source_median;source_count={len(candidates)};"
        f"sources={sources};analyst_count_total="
        f"{analyst_total if analyst_total else 'unknown'}"
    )
    datums: dict[str, MarketDatum] = {
        "target_mean_price": MarketDatum(
            value=target_median,
            source=FREE_CONSENSUS_AGGREGATE_SOURCE,
            as_of=as_of,
            horizon="12m",
            source_detail=source_detail,
            quality_flags=tuple(dict.fromkeys(quality_flags)),
            license_note=(
                "Derived from free/public web analyst consensus sources. "
                "Verify source terms before redistribution."
            ),
        )
    }

    if highs:
        datums["target_high_price"] = MarketDatum(
            value=float(median(highs)),
            source=FREE_CONSENSUS_AGGREGATE_SOURCE,
            as_of=as_of,
            horizon="12m",
            source_detail=source_detail,
            quality_flags=("aggregated",),
            license_note=datums["target_mean_price"].license_note,
        )
    if lows:
        datums["target_low_price"] = MarketDatum(
            value=float(median(lows)),
            source=FREE_CONSENSUS_AGGREGATE_SOURCE,
            as_of=as_of,
            horizon="12m",
            source_detail=source_detail,
            quality_flags=("aggregated",),
            license_note=datums["target_mean_price"].license_note,
        )
    if analyst_total > 0:
        datums["target_analyst_count"] = MarketDatum(
            value=float(analyst_total),
            source=FREE_CONSENSUS_AGGREGATE_SOURCE,
            as_of=as_of,
            horizon="12m",
            source_detail=source_detail,
            quality_flags=("aggregated",),
            license_note=datums["target_mean_price"].license_note,
        )

    return ConsensusAnchorAggregateResult(datums=datums, warnings=tuple(warnings))


def _target_consensus_max_age_days() -> int:
    return _read_env_int(
        "FUNDAMENTAL_TARGET_CONSENSUS_MAX_AGE_DAYS",
        DEFAULT_TARGET_CONSENSUS_MAX_AGE_DAYS,
    )


def _target_consensus_min_analyst_count() -> int:
    return _read_env_int(
        "FUNDAMENTAL_TARGET_CONSENSUS_MIN_ANALYST_COUNT",
        DEFAULT_TARGET_CONSENSUS_MIN_ANALYST_COUNT,
    )


def _target_consensus_min_sources() -> int:
    return _read_env_int(
        "FUNDAMENTAL_TARGET_CONSENSUS_MIN_SOURCES",
        DEFAULT_TARGET_CONSENSUS_MIN_SOURCES,
    )


def _read_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        parsed = int(float(raw))
    except ValueError:
        return default
    return max(parsed, 0)


def _to_float(datum: MarketDatum | None) -> float | None:
    if datum is None:
        return None
    return datum.value


def _to_analyst_count(datum: MarketDatum | None) -> int | None:
    if datum is None:
        return None
    value = datum.value
    if value is None:
        return None
    if value < 0:
        return None
    return int(round(value))


def _latest_as_of(values: Iterable[str | None]) -> str | None:
    parsed_candidates: list[tuple[datetime, str]] = []
    for item in values:
        parsed = _parse_as_of(item)
        if parsed is None or item is None:
            continue
        parsed_candidates.append((parsed, item))
    if not parsed_candidates:
        return None
    parsed_candidates.sort(key=lambda pair: pair[0])
    return parsed_candidates[-1][1]


def _staleness_days(as_of: str | None, *, now: datetime) -> int | None:
    parsed = _parse_as_of(as_of)
    if parsed is None:
        return None
    return int((now.date() - parsed.date()).days)


def _parse_as_of(as_of: str | None) -> datetime | None:
    if not isinstance(as_of, str) or not as_of.strip():
        return None
    normalized = as_of.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
