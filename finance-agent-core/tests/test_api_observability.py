from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from api.server import app, get_observability_runtime
from src.agents.technical.subdomains.calibration.domain.contracts import (
    TechnicalDirectionCalibrationObservation,
)
from src.agents.technical.subdomains.decision_observability.domain import (
    TechnicalCalibrationObservationBuildResult,
    TechnicalMonitoringAggregate,
    TechnicalMonitoringEventDetail,
    TechnicalMonitoringReadModelRow,
)


@pytest.fixture
def mock_runtime():
    runtime = Mock()
    runtime.load_monitoring_aggregates = AsyncMock()
    runtime.load_monitoring_rows = AsyncMock()
    runtime.load_monitoring_event_detail = AsyncMock()
    runtime.load_direction_calibration_observations = AsyncMock()
    return runtime


@pytest.fixture
async def client(mock_runtime):
    app.dependency_overrides[get_observability_runtime] = lambda: mock_runtime
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_monitoring_aggregates(client, mock_runtime):
    mock_runtime.load_monitoring_aggregates.return_value = (
        TechnicalMonitoringAggregate(
            timeframe="1d",
            horizon="10d",
            logic_version="v1",
            event_count=10,
            labeled_event_count=5,
            unresolved_event_count=5,
            avg_confidence=0.8,
            avg_raw_score=0.5,
            avg_forward_return=0.1,
            avg_mfe=0.2,
            avg_mae=-0.1,
            avg_realized_volatility=0.05,
            first_event_time=datetime(2026, 1, 1),
            last_event_time=datetime(2026, 1, 10),
        ),
    )

    response = await client.get(
        "/api/observability/monitoring/aggregates",
        params={
            "tickers": "AAPL",
            "agent_sources": "technical_analysis",
            "timeframes": "1d",
            "reliability_levels": "high",
            "event_time_start": "2026-01-01T00:00:00Z",
            "resolved_time_end": "2026-01-31T08:00:00+08:00",
            "labeling_method_version": "technical_outcome_labeling.v2",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["timeframe"] == "1d"
    assert data[0]["horizon"] == "10d"
    assert data[0]["event_count"] == 10

    # Verify scope extraction
    scope = mock_runtime.load_monitoring_aggregates.call_args[1]["scope"]
    assert scope.tickers == ("AAPL",)
    assert scope.agent_sources == ("technical_analysis",)
    assert scope.timeframes == ("1d",)
    assert scope.reliability_levels == ("high",)
    assert scope.event_time_start == datetime(2026, 1, 1, 0, 0)
    assert scope.resolved_time_end == datetime(2026, 1, 31, 0, 0)
    assert scope.event_time_start.tzinfo is None
    assert scope.resolved_time_end.tzinfo is None
    assert scope.labeling_method_version == "technical_outcome_labeling.v2"


@pytest.mark.asyncio
async def test_get_monitoring_rows(client, mock_runtime):
    mock_runtime.load_monitoring_rows.return_value = (
        TechnicalMonitoringReadModelRow(
            event_id="evt-1",
            event_time=datetime(2026, 1, 1),
            ticker="AAPL",
            agent_source="test_agent",
            timeframe="1d",
            horizon="10d",
            direction="bullish",
            logic_version="v1",
            run_type="automation",
            reliability_level="high",
            raw_score=0.8,
            confidence=0.9,
            outcome_path_id=None,
            resolved_at=None,
            labeling_method_version=None,
            forward_return=None,
            mfe=None,
            mae=None,
            realized_volatility=None,
            data_quality_flags=("ok",),
        ),
    )

    response = await client.get("/api/observability/monitoring/rows?limit=50")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["event_id"] == "evt-1"
    assert data[0]["ticker"] == "AAPL"

    scope = mock_runtime.load_monitoring_rows.call_args[1]["scope"]
    assert scope.limit == 50


@pytest.mark.asyncio
async def test_get_monitoring_event_detail(client, mock_runtime):
    mock_runtime.load_monitoring_event_detail.return_value = (
        TechnicalMonitoringEventDetail(
            event_id="evt-1",
            event_time=datetime(2026, 1, 1),
            ticker="AAPL",
            agent_source="technical_analysis",
            timeframe="1d",
            horizon="10d",
            direction="bullish",
            logic_version="v1",
            feature_contract_version="technical_feature_contract_v1",
            run_type="workflow",
            reliability_level="high",
            raw_score=0.8,
            confidence=0.9,
            full_report_artifact_id="art-1",
            source_artifact_refs={"fusion_report_id": "fusion-1"},
            context_payload={"volatility_regime": "high"},
            outcome_path_id="outcome-1",
            resolved_at=datetime(2026, 1, 11),
            labeling_method_version="technical_outcome_labeling.v1",
            forward_return=0.1,
            mfe=0.2,
            mae=-0.1,
            realized_volatility=0.05,
            data_quality_flags=("ok",),
        )
    )

    response = await client.get(
        "/api/observability/monitoring/events/evt-1"
        "?labeling_method_version=technical_outcome_labeling.v2"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["event_id"] == "evt-1"
    assert data["full_report_artifact_id"] == "art-1"
    assert data["source_artifact_refs"]["fusion_report_id"] == "fusion-1"

    call = mock_runtime.load_monitoring_event_detail.call_args[1]
    assert call["event_id"] == "evt-1"
    assert call["labeling_method_version"] == "technical_outcome_labeling.v2"


@pytest.mark.asyncio
async def test_get_direction_calibration_readiness(client, mock_runtime):
    mock_runtime.load_direction_calibration_observations.return_value = (
        TechnicalCalibrationObservationBuildResult(
            observations=(
                TechnicalDirectionCalibrationObservation(
                    timeframe="1d",
                    horizon="10d",
                    raw_score=0.8,
                    direction="bullish",
                    target_outcome=0.1,
                ),
            ),
            row_count=10,
            usable_row_count=1,
            dropped_row_count=9,
            dropped_reasons={"missing_outcome_path": 9},
        )
    )

    # Test without observations (default)
    response = await client.get(
        "/api/observability/calibration/direction-readiness?tickers=TSLA"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["row_count"] == 10
    assert data["dropped_row_count"] == 9
    assert data["observations"] is None

    # Test with observations
    response2 = await client.get(
        "/api/observability/calibration/direction-readiness?include_observations=true"
    )
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["observations"] is not None
    assert len(data2["observations"]) == 1
    assert data2["observations"][0]["direction"] == "bullish"


@pytest.mark.asyncio
async def test_invalid_query_and_empty_responses(client, mock_runtime):
    mock_runtime.load_monitoring_rows.return_value = ()
    mock_runtime.load_monitoring_event_detail.return_value = None

    # Empty response
    response = await client.get("/api/observability/monitoring/rows?tickers=UNKNOWN")
    assert response.status_code == 200
    assert response.json() == []

    # Limit clamp
    response2 = await client.get("/api/observability/monitoring/rows?limit=100000")
    assert response2.status_code == 200
    scope = mock_runtime.load_monitoring_rows.call_args[1]["scope"]
    assert scope.limit == 1000

    response3 = await client.get("/api/observability/monitoring/events/missing")
    assert response3.status_code == 404
    assert response3.json() == {"detail": "Observability event not found"}
