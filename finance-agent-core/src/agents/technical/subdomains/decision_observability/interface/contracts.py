from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from src.agents.technical.subdomains.decision_observability.domain import (
    TechnicalMonitoringAggregate,
    TechnicalMonitoringReadModelRow,
)


class TechnicalMonitoringRowModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    event_time: datetime
    ticker: str
    agent_source: str
    timeframe: str
    horizon: str
    direction: str
    logic_version: str
    run_type: str
    reliability_level: str | None = None
    raw_score: float | None = None
    confidence: float | None = None
    outcome_path_id: str | None = None
    resolved_at: datetime | None = None
    labeling_method_version: str | None = None
    forward_return: float | None = None
    mfe: float | None = None
    mae: float | None = None
    realized_volatility: float | None = None
    data_quality_flags: list[str]


class TechnicalMonitoringAggregateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeframe: str
    horizon: str
    logic_version: str
    event_count: int
    labeled_event_count: int
    unresolved_event_count: int
    avg_confidence: float | None = None
    avg_raw_score: float | None = None
    avg_forward_return: float | None = None
    avg_mfe: float | None = None
    avg_mae: float | None = None
    avg_realized_volatility: float | None = None
    first_event_time: datetime | None = None
    last_event_time: datetime | None = None


def build_technical_monitoring_row_model(
    record: TechnicalMonitoringReadModelRow,
) -> TechnicalMonitoringRowModel:
    return TechnicalMonitoringRowModel(
        event_id=record.event_id,
        event_time=record.event_time,
        ticker=record.ticker,
        agent_source=record.agent_source,
        timeframe=record.timeframe,
        horizon=record.horizon,
        direction=record.direction,
        logic_version=record.logic_version,
        run_type=record.run_type,
        reliability_level=record.reliability_level,
        raw_score=record.raw_score,
        confidence=record.confidence,
        outcome_path_id=record.outcome_path_id,
        resolved_at=record.resolved_at,
        labeling_method_version=record.labeling_method_version,
        forward_return=record.forward_return,
        mfe=record.mfe,
        mae=record.mae,
        realized_volatility=record.realized_volatility,
        data_quality_flags=list(record.data_quality_flags),
    )


def build_technical_monitoring_aggregate_model(
    record: TechnicalMonitoringAggregate,
) -> TechnicalMonitoringAggregateModel:
    return TechnicalMonitoringAggregateModel(
        timeframe=record.timeframe,
        horizon=record.horizon,
        logic_version=record.logic_version,
        event_count=record.event_count,
        labeled_event_count=record.labeled_event_count,
        unresolved_event_count=record.unresolved_event_count,
        avg_confidence=record.avg_confidence,
        avg_raw_score=record.avg_raw_score,
        avg_forward_return=record.avg_forward_return,
        avg_mfe=record.avg_mfe,
        avg_mae=record.avg_mae,
        avg_realized_volatility=record.avg_realized_volatility,
        first_event_time=record.first_event_time,
        last_event_time=record.last_event_time,
    )
