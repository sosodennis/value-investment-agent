from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .contracts import (
    MonitoringQueryScope,
    TechnicalMonitoringAggregate,
    TechnicalMonitoringReadModelRow,
)

_DEFAULT_MONITORING_LIMIT = 200
_MAX_MONITORING_LIMIT = 1000


def build_monitoring_query_scope(
    *,
    tickers: tuple[str, ...] | list[str] = (),
    agent_sources: tuple[str, ...] | list[str] = (),
    timeframes: tuple[str, ...] | list[str] = (),
    horizons: tuple[str, ...] | list[str] = (),
    logic_versions: tuple[str, ...] | list[str] = (),
    directions: tuple[str, ...] | list[str] = (),
    run_types: tuple[str, ...] | list[str] = (),
    reliability_levels: tuple[str, ...] | list[str] = (),
    event_time_start: datetime | None = None,
    event_time_end: datetime | None = None,
    resolved_time_start: datetime | None = None,
    resolved_time_end: datetime | None = None,
    labeling_method_version: str = "technical_outcome_labeling.v1",
    limit: int = _DEFAULT_MONITORING_LIMIT,
) -> MonitoringQueryScope:
    return MonitoringQueryScope(
        tickers=_normalize_filter_values(tickers),
        agent_sources=_normalize_filter_values(agent_sources),
        timeframes=_normalize_filter_values(timeframes),
        horizons=_normalize_filter_values(horizons),
        logic_versions=_normalize_filter_values(logic_versions),
        directions=_normalize_filter_values(directions),
        run_types=_normalize_filter_values(run_types),
        reliability_levels=_normalize_filter_values(reliability_levels),
        event_time_start=event_time_start,
        event_time_end=event_time_end,
        resolved_time_start=resolved_time_start,
        resolved_time_end=resolved_time_end,
        labeling_method_version=labeling_method_version.strip()
        or "technical_outcome_labeling.v1",
        limit=_normalize_limit(limit),
    )


def compute_monitoring_aggregates(
    rows: tuple[TechnicalMonitoringReadModelRow, ...]
    | list[TechnicalMonitoringReadModelRow],
) -> tuple[TechnicalMonitoringAggregate, ...]:
    grouped: dict[tuple[str, str, str], _AggregateAccumulator] = {}

    for row in rows:
        key = (row.timeframe, row.horizon, row.logic_version)
        accumulator = grouped.get(key)
        if accumulator is None:
            accumulator = _AggregateAccumulator(
                timeframe=row.timeframe,
                horizon=row.horizon,
                logic_version=row.logic_version,
            )
            grouped[key] = accumulator
        accumulator.observe(row)

    aggregates = [accumulator.build() for accumulator in grouped.values()]
    aggregates.sort(
        key=lambda aggregate: (
            aggregate.timeframe,
            aggregate.horizon,
            aggregate.logic_version,
        )
    )
    return tuple(aggregates)


def _normalize_filter_values(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return tuple(normalized)


def _normalize_limit(limit: int) -> int:
    if limit <= 0:
        return _DEFAULT_MONITORING_LIMIT
    return min(limit, _MAX_MONITORING_LIMIT)


@dataclass
class _MetricAverage:
    total: float = 0.0
    count: int = 0

    def observe(self, value: float | None) -> None:
        if value is None:
            return
        self.total += value
        self.count += 1

    def value(self) -> float | None:
        if self.count <= 0:
            return None
        return self.total / self.count


@dataclass
class _AggregateAccumulator:
    timeframe: str
    horizon: str
    logic_version: str
    event_count: int = 0
    labeled_event_count: int = 0
    unresolved_event_count: int = 0
    confidence: _MetricAverage = field(default_factory=_MetricAverage)
    raw_score: _MetricAverage = field(default_factory=_MetricAverage)
    forward_return: _MetricAverage = field(default_factory=_MetricAverage)
    mfe: _MetricAverage = field(default_factory=_MetricAverage)
    mae: _MetricAverage = field(default_factory=_MetricAverage)
    realized_volatility: _MetricAverage = field(default_factory=_MetricAverage)
    first_event_time: datetime | None = None
    last_event_time: datetime | None = None

    def observe(self, row: TechnicalMonitoringReadModelRow) -> None:
        self.event_count += 1
        if row.outcome_path_id is None:
            self.unresolved_event_count += 1
        else:
            self.labeled_event_count += 1

        self.confidence.observe(row.confidence)
        self.raw_score.observe(row.raw_score)
        self.forward_return.observe(row.forward_return)
        self.mfe.observe(row.mfe)
        self.mae.observe(row.mae)
        self.realized_volatility.observe(row.realized_volatility)

        if self.first_event_time is None or row.event_time < self.first_event_time:
            self.first_event_time = row.event_time
        if self.last_event_time is None or row.event_time > self.last_event_time:
            self.last_event_time = row.event_time

    def build(self) -> TechnicalMonitoringAggregate:
        return TechnicalMonitoringAggregate(
            timeframe=self.timeframe,
            horizon=self.horizon,
            logic_version=self.logic_version,
            event_count=self.event_count,
            labeled_event_count=self.labeled_event_count,
            unresolved_event_count=self.unresolved_event_count,
            avg_confidence=self.confidence.value(),
            avg_raw_score=self.raw_score.value(),
            avg_forward_return=self.forward_return.value(),
            avg_mfe=self.mfe.value(),
            avg_mae=self.mae.value(),
            avg_realized_volatility=self.realized_volatility.value(),
            first_event_time=self.first_event_time,
            last_event_time=self.last_event_time,
        )
