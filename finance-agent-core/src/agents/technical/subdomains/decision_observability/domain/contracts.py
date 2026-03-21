from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class TechnicalPredictionEventRecord:
    event_id: str
    agent_source: str
    event_time: datetime
    ticker: str
    timeframe: str
    horizon: str
    direction: str
    raw_score: float | None
    confidence: float | None
    reliability_level: str | None
    logic_version: str
    feature_contract_version: str
    run_type: str
    full_report_artifact_id: str
    source_artifact_refs: JSONObject
    context_payload: JSONObject


@dataclass(frozen=True)
class TechnicalOutcomePathRecord:
    outcome_path_id: str
    event_id: str
    resolved_at: datetime
    forward_return: float | None
    mfe: float | None
    mae: float | None
    realized_volatility: float | None
    labeling_method_version: str
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class TechnicalApprovedLabelSnapshotRecord:
    snapshot_id: str
    event_id: str
    agent_source: str
    label_family: str
    label_method_version: str
    approved_at: datetime
    approved_by: str
    definition_hash: str
    labels_payload: JSONObject


@dataclass(frozen=True)
class OutcomeLabelingRequest:
    event: TechnicalPredictionEventRecord
    as_of_time: datetime
    maturity_time: datetime
    labeling_method_version: str
    interval: str = "1d"
    period: str = "6mo"


@dataclass(frozen=True)
class OutcomeLabelingResult:
    outcome: TechnicalOutcomePathRecord
    source_row_count: int
    entry_time: datetime
    exit_time: datetime
    is_matured: bool
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class HorizonResolution:
    horizon: str
    delta: timedelta


@dataclass(frozen=True)
class MonitoringQueryScope:
    tickers: tuple[str, ...] = ()
    agent_sources: tuple[str, ...] = ()
    timeframes: tuple[str, ...] = ()
    horizons: tuple[str, ...] = ()
    logic_versions: tuple[str, ...] = ()
    directions: tuple[str, ...] = ()
    run_types: tuple[str, ...] = ()
    reliability_levels: tuple[str, ...] = ()
    event_time_start: datetime | None = None
    event_time_end: datetime | None = None
    resolved_time_start: datetime | None = None
    resolved_time_end: datetime | None = None
    labeling_method_version: str = "technical_outcome_labeling.v1"
    limit: int = 200


@dataclass(frozen=True)
class TechnicalMonitoringReadModelRow:
    event_id: str
    event_time: datetime
    ticker: str
    agent_source: str
    timeframe: str
    horizon: str
    direction: str
    logic_version: str
    run_type: str
    reliability_level: str | None
    raw_score: float | None
    confidence: float | None
    outcome_path_id: str | None
    resolved_at: datetime | None
    labeling_method_version: str | None
    forward_return: float | None
    mfe: float | None
    mae: float | None
    realized_volatility: float | None
    data_quality_flags: tuple[str, ...]


@dataclass(frozen=True)
class TechnicalMonitoringAggregate:
    timeframe: str
    horizon: str
    logic_version: str
    event_count: int
    labeled_event_count: int
    unresolved_event_count: int
    avg_confidence: float | None
    avg_raw_score: float | None
    avg_forward_return: float | None
    avg_mfe: float | None
    avg_mae: float | None
    avg_realized_volatility: float | None
    first_event_time: datetime | None
    last_event_time: datetime | None
