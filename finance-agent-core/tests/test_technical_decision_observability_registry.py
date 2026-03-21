from __future__ import annotations

from datetime import datetime

import pytest

from src.agents.technical.subdomains.decision_observability import (
    SqlAlchemyTechnicalDecisionObservabilityRepository,
    build_prediction_event_record,
)
from src.infrastructure.database import Base
from src.infrastructure.models import (
    TechnicalApprovedLabelSnapshot,
    TechnicalOutcomePath,
    TechnicalPredictionEvent,
)


def test_build_prediction_event_record_uses_report_payload_and_defaults() -> None:
    record = build_prediction_event_record(
        ticker="AAPL",
        technical_context={
            "confidence_calibrated": 0.64,
            "signal_strength_raw": 0.58,
            "setup_reliability_summary": {"level": "high"},
            "quality_summary": {"is_degraded": False},
        },
        full_report_payload={
            "schema_version": "2.0",
            "as_of": "2026-03-20T20:00:00Z",
            "direction": "BULLISH_EXTENSION",
            "summary_tags": ["TREND_ACTIVE"],
            "artifact_refs": {
                "feature_pack_id": "feature-1",
                "fusion_report_id": "fusion-1",
            },
            "evidence_bundle": {
                "primary_timeframe": "1d",
                "support_levels": [180.5],
                "resistance_levels": [190.2],
                "conflict_reasons": ["LOW_CONFLUENCE"],
            },
        },
        report_artifact_id="report-1",
        run_type="workflow",
    )

    assert record.ticker == "AAPL"
    assert record.timeframe == "1d"
    assert record.horizon == "5d"
    assert record.direction == "BULLISH_EXTENSION"
    assert record.raw_score == pytest.approx(0.58)
    assert record.confidence == pytest.approx(0.64)
    assert record.reliability_level == "high"
    assert record.logic_version == "technical_decision_registry.v1"
    assert record.feature_contract_version == "technical_artifact_schema:2.0"
    assert record.full_report_artifact_id == "report-1"
    assert record.source_artifact_refs["feature_pack_id"] == "feature-1"
    assert record.context_payload["summary_tags"] == ["TREND_ACTIVE"]
    assert record.context_payload["evidence_bundle"]["conflict_reasons"] == [
        "LOW_CONFLUENCE"
    ]
    assert isinstance(record.event_time, datetime)


def test_build_prediction_event_record_uses_explicit_supported_horizon() -> None:
    record = build_prediction_event_record(
        ticker="MSFT",
        technical_context={"target_horizon": "20d"},
        full_report_payload={"schema_version": "2.0", "direction": "NEUTRAL"},
        report_artifact_id="report-2",
        run_type="replay",
    )

    assert record.horizon == "20d"
    assert record.timeframe == "1d"
    assert record.run_type == "replay"


@pytest.mark.asyncio
async def test_repository_appends_prediction_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []
            self.committed = False

        def add(self, obj: object) -> None:
            self.added.append(obj)

        async def commit(self) -> None:
            self.committed = True

    class _FakeSessionContext:
        def __init__(self, session: _FakeSession) -> None:
            self._session = session

        async def __aenter__(self) -> _FakeSession:
            return self._session

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

    fake_session = _FakeSession()

    monkeypatch.setattr(
        "src.agents.technical.subdomains.decision_observability.infrastructure.repository.AsyncSessionLocal",
        lambda: _FakeSessionContext(fake_session),
    )

    repository = SqlAlchemyTechnicalDecisionObservabilityRepository()
    record = build_prediction_event_record(
        ticker="NVDA",
        technical_context={"confidence": 0.71},
        full_report_payload={"schema_version": "2.0", "direction": "BULLISH"},
        report_artifact_id="report-3",
        run_type="workflow",
    )

    await repository.append_prediction_event(record)

    assert fake_session.committed is True
    assert len(fake_session.added) == 1
    model = fake_session.added[0]
    assert isinstance(model, TechnicalPredictionEvent)
    assert model.event_id == record.event_id
    assert model.full_report_artifact_id == "report-3"
    assert model.direction == "BULLISH"


def test_decision_observability_models_registered_in_metadata() -> None:
    tables = Base.metadata.tables

    assert TechnicalPredictionEvent.__tablename__ in tables
    assert TechnicalOutcomePath.__tablename__ in tables
    assert TechnicalApprovedLabelSnapshot.__tablename__ in tables

    prediction_table = tables[TechnicalPredictionEvent.__tablename__]
    outcome_table = tables[TechnicalOutcomePath.__tablename__]
    snapshot_table = tables[TechnicalApprovedLabelSnapshot.__tablename__]

    prediction_fk_targets = {
        foreign_key.column.table.name
        for foreign_key in prediction_table.c.full_report_artifact_id.foreign_keys
    }
    outcome_fk_targets = {
        foreign_key.column.table.name
        for foreign_key in outcome_table.c.event_id.foreign_keys
    }
    snapshot_fk_targets = {
        foreign_key.column.table.name
        for foreign_key in snapshot_table.c.event_id.foreign_keys
    }

    assert prediction_fk_targets == {"artifacts"}
    assert outcome_fk_targets == {"technical_prediction_events"}
    assert snapshot_fk_targets == {"technical_prediction_events"}
