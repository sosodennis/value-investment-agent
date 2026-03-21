from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from src.agents.technical.subdomains.decision_observability import (
    MonitoringQueryScope,
    TechnicalDecisionObservabilityRuntimeService,
    TechnicalMonitoringReadModelRow,
    TechnicalMonitoringRowModel,
    build_monitoring_query_scope,
    build_technical_monitoring_aggregate_model,
    build_technical_monitoring_row_model,
    compute_monitoring_aggregates,
)
from src.agents.technical.subdomains.decision_observability.infrastructure import (
    SqlAlchemyTechnicalDecisionObservabilityRepository,
)
from src.infrastructure.models import TechnicalOutcomePath, TechnicalPredictionEvent


def _row(
    *,
    event_id: str,
    timeframe: str,
    horizon: str,
    logic_version: str,
    event_time: datetime,
    confidence: float | None,
    raw_score: float | None,
    outcome_path_id: str | None = None,
    forward_return: float | None = None,
    mfe: float | None = None,
    mae: float | None = None,
    realized_volatility: float | None = None,
) -> TechnicalMonitoringReadModelRow:
    return TechnicalMonitoringReadModelRow(
        event_id=event_id,
        event_time=event_time,
        ticker="AAPL",
        agent_source="technical",
        timeframe=timeframe,
        horizon=horizon,
        direction="BULLISH_EXTENSION",
        logic_version=logic_version,
        run_type="workflow",
        reliability_level="HIGH",
        raw_score=raw_score,
        confidence=confidence,
        outcome_path_id=outcome_path_id,
        resolved_at=None if outcome_path_id is None else datetime(2026, 3, 20),
        labeling_method_version=(
            None if outcome_path_id is None else "technical_outcome_labeling.v1"
        ),
        forward_return=forward_return,
        mfe=mfe,
        mae=mae,
        realized_volatility=realized_volatility,
        data_quality_flags=(),
    )


def test_build_monitoring_query_scope_normalizes_filters_and_limit() -> None:
    scope = build_monitoring_query_scope(
        tickers=["AAPL", "AAPL", " "],
        timeframes=["1d", "1d", "4h"],
        logic_versions=["logic.v2", ""],
        limit=5000,
    )

    assert scope == MonitoringQueryScope(
        tickers=("AAPL",),
        agent_sources=(),
        timeframes=("1d", "4h"),
        horizons=(),
        logic_versions=("logic.v2",),
        directions=(),
        run_types=(),
        reliability_levels=(),
        event_time_start=None,
        event_time_end=None,
        resolved_time_start=None,
        resolved_time_end=None,
        labeling_method_version="technical_outcome_labeling.v1",
        limit=1000,
    )


def test_compute_monitoring_aggregates_groups_rows_by_required_dimensions() -> None:
    aggregates = compute_monitoring_aggregates(
        [
            _row(
                event_id="event-1",
                timeframe="1d",
                horizon="5d",
                logic_version="logic.v1",
                event_time=datetime(2026, 3, 10),
                confidence=0.7,
                raw_score=0.8,
                outcome_path_id="outcome-1",
                forward_return=0.04,
                mfe=0.06,
                mae=-0.02,
                realized_volatility=0.22,
            ),
            _row(
                event_id="event-2",
                timeframe="1d",
                horizon="5d",
                logic_version="logic.v1",
                event_time=datetime(2026, 3, 11),
                confidence=0.9,
                raw_score=0.6,
            ),
            _row(
                event_id="event-3",
                timeframe="4h",
                horizon="1d",
                logic_version="logic.v2",
                event_time=datetime(2026, 3, 9),
                confidence=0.5,
                raw_score=0.4,
                outcome_path_id="outcome-3",
                forward_return=-0.01,
                mfe=0.02,
                mae=-0.03,
                realized_volatility=0.4,
            ),
        ]
    )

    assert len(aggregates) == 2

    first = aggregates[0]
    assert first.timeframe == "1d"
    assert first.horizon == "5d"
    assert first.logic_version == "logic.v1"
    assert first.event_count == 2
    assert first.labeled_event_count == 1
    assert first.unresolved_event_count == 1
    assert first.avg_confidence == pytest.approx(0.8)
    assert first.avg_raw_score == pytest.approx(0.7)
    assert first.avg_forward_return == pytest.approx(0.04)
    assert first.first_event_time == datetime(2026, 3, 10)
    assert first.last_event_time == datetime(2026, 3, 11)

    second = aggregates[1]
    assert second.timeframe == "4h"
    assert second.horizon == "1d"
    assert second.logic_version == "logic.v2"
    assert second.event_count == 1
    assert second.labeled_event_count == 1
    assert second.unresolved_event_count == 0
    assert second.avg_forward_return == pytest.approx(-0.01)


@pytest.mark.asyncio
async def test_repository_fetch_monitoring_rows_returns_joined_truth_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_model = TechnicalPredictionEvent(
        event_id="event-1",
        agent_source="technical",
        event_time=datetime(2026, 3, 10, tzinfo=UTC).replace(tzinfo=None),
        ticker="AAPL",
        timeframe="1d",
        horizon="5d",
        direction="BULLISH_EXTENSION",
        raw_score=0.8,
        confidence=0.75,
        reliability_level="HIGH",
        logic_version="logic.v1",
        feature_contract_version="feature.v1",
        run_type="workflow",
        full_report_artifact_id="artifact-1",
        source_artifact_refs={},
        context_payload={},
    )
    outcome_model = TechnicalOutcomePath(
        outcome_path_id="outcome-1",
        event_id="event-1",
        resolved_at=datetime(2026, 3, 20),
        forward_return=0.05,
        mfe=0.07,
        mae=-0.01,
        realized_volatility=0.2,
        labeling_method_version="technical_outcome_labeling.v1",
        data_quality_flags=["SHORT_WINDOW"],
    )

    class _ExecuteResult:
        def all(self) -> list[tuple[object, object | None]]:
            return [(event_model, outcome_model)]

    class _FakeSession:
        async def execute(self, _query: object) -> _ExecuteResult:
            return _ExecuteResult()

    class _FakeSessionContext:
        async def __aenter__(self) -> _FakeSession:
            return _FakeSession()

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    monkeypatch.setattr(
        "src.agents.technical.subdomains.decision_observability.infrastructure.repository.AsyncSessionLocal",
        lambda: _FakeSessionContext(),
    )

    repository = SqlAlchemyTechnicalDecisionObservabilityRepository()
    rows = await repository.fetch_monitoring_rows(
        scope=build_monitoring_query_scope(tickers=["AAPL"])
    )

    assert len(rows) == 1
    assert rows[0].event_id == "event-1"
    assert rows[0].outcome_path_id == "outcome-1"
    assert rows[0].labeling_method_version == "technical_outcome_labeling.v1"
    assert rows[0].data_quality_flags == ("SHORT_WINDOW",)


@pytest.mark.asyncio
async def test_runtime_load_monitoring_aggregates_from_repository_rows() -> None:
    @dataclass
    class _FakeRepository:
        rows: list[TechnicalMonitoringReadModelRow]

        async def append_prediction_event(self, record: object) -> None:
            raise AssertionError("not used")

        async def fetch_unlabeled_prediction_events(
            self, *, labeling_method_version: str, limit: int = 100
        ) -> list[object]:
            raise AssertionError("not used")

        async def append_outcome_path_if_missing(
            self, *, request: object, outcome: object
        ) -> bool:
            raise AssertionError("not used")

        async def fetch_monitoring_rows(
            self,
            *,
            scope: MonitoringQueryScope,
        ) -> list[TechnicalMonitoringReadModelRow]:
            assert scope.tickers == ("AAPL",)
            return self.rows

    runtime = TechnicalDecisionObservabilityRuntimeService(
        repository=_FakeRepository(
            rows=[
                _row(
                    event_id="event-1",
                    timeframe="1d",
                    horizon="5d",
                    logic_version="logic.v1",
                    event_time=datetime(2026, 3, 10),
                    confidence=0.7,
                    raw_score=0.8,
                    outcome_path_id="outcome-1",
                    forward_return=0.04,
                ),
                _row(
                    event_id="event-2",
                    timeframe="1d",
                    horizon="5d",
                    logic_version="logic.v1",
                    event_time=datetime(2026, 3, 11),
                    confidence=0.9,
                    raw_score=0.6,
                ),
            ]
        )
    )

    aggregates = await runtime.load_monitoring_aggregates(
        scope=build_monitoring_query_scope(tickers=["AAPL"])
    )

    assert len(aggregates) == 1
    assert aggregates[0].event_count == 2
    assert aggregates[0].labeled_event_count == 1


def test_interface_models_build_from_monitoring_records() -> None:
    row = _row(
        event_id="event-1",
        timeframe="1d",
        horizon="5d",
        logic_version="logic.v1",
        event_time=datetime(2026, 3, 10),
        confidence=0.7,
        raw_score=0.8,
        outcome_path_id="outcome-1",
        forward_return=0.04,
        mfe=0.06,
        mae=-0.02,
        realized_volatility=0.22,
    )
    aggregate = compute_monitoring_aggregates([row])[0]

    row_model = build_technical_monitoring_row_model(row)
    aggregate_model = build_technical_monitoring_aggregate_model(aggregate)

    assert isinstance(row_model, TechnicalMonitoringRowModel)
    assert row_model.data_quality_flags == []
    assert aggregate_model.event_count == 1
    assert aggregate_model.avg_forward_return == pytest.approx(0.04)
