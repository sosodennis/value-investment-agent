from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.agents.technical.subdomains.calibration import (
    TechnicalDirectionCalibrationObservation,
    build_technical_direction_calibration_observations,
)
from src.agents.technical.subdomains.decision_observability import (
    TechnicalDecisionObservabilityRuntimeService,
    build_monitoring_query_scope,
)
from src.agents.technical.subdomains.decision_observability.domain.contracts import (
    MonitoringQueryScope,
    TechnicalMonitoringReadModelRow,
)


def _row(
    *,
    event_id: str,
    direction: str = "BULLISH_EXTENSION",
    raw_score: float | None = 0.8,
    forward_return: float | None = 0.04,
    outcome_path_id: str | None = "outcome-1",
) -> TechnicalMonitoringReadModelRow:
    return TechnicalMonitoringReadModelRow(
        event_id=event_id,
        event_time=datetime(2026, 3, 10),
        ticker="AAPL",
        agent_source="technical",
        timeframe="1d",
        horizon="5d",
        direction=direction,
        logic_version="logic.v1",
        run_type="workflow",
        reliability_level="HIGH",
        raw_score=raw_score,
        confidence=0.7,
        outcome_path_id=outcome_path_id,
        resolved_at=None if outcome_path_id is None else datetime(2026, 3, 20),
        labeling_method_version=(
            None if outcome_path_id is None else "technical_outcome_labeling.v1"
        ),
        forward_return=forward_return,
        mfe=0.06,
        mae=-0.02,
        realized_volatility=0.2,
        data_quality_flags=(),
    )


def test_builder_converts_monitoring_rows_to_calibration_observations() -> None:
    result = build_technical_direction_calibration_observations(
        [
            _row(event_id="event-1", direction="BULLISH_EXTENSION"),
            _row(
                event_id="event-2", direction="BEARISH_BREAKDOWN", forward_return=-0.03
            ),
        ]
    )

    assert result.row_count == 2
    assert result.usable_row_count == 2
    assert result.dropped_row_count == 0
    assert result.dropped_reasons == {}
    assert result.observations == (
        TechnicalDirectionCalibrationObservation(
            timeframe="1d",
            horizon="5d",
            raw_score=0.8,
            direction="bullish",
            target_outcome=0.04,
        ),
        TechnicalDirectionCalibrationObservation(
            timeframe="1d",
            horizon="5d",
            raw_score=0.8,
            direction="bearish",
            target_outcome=-0.03,
        ),
    )


def test_builder_tracks_drop_reasons_for_unusable_rows() -> None:
    result = build_technical_direction_calibration_observations(
        [
            _row(event_id="event-1", outcome_path_id=None),
            _row(event_id="event-2", raw_score=None),
            _row(event_id="event-3", forward_return=None),
            _row(event_id="event-4", direction="NEUTRAL_CONSOLIDATION"),
        ]
    )

    assert result.row_count == 4
    assert result.usable_row_count == 0
    assert result.dropped_row_count == 4
    assert result.dropped_reasons == {
        "missing_outcome_path": 1,
        "missing_raw_score": 1,
        "missing_forward_return": 1,
        "unsupported_direction_family": 1,
    }


async def test_runtime_load_direction_calibration_observations_from_monitoring_rows() -> (
    None
):
    @dataclass
    class _FakeRepository:
        rows: list[TechnicalMonitoringReadModelRow]

        async def append_prediction_event(self, record: object) -> None:
            raise AssertionError("not used")

        async def fetch_unlabeled_prediction_events(
            self,
            *,
            labeling_method_version: str,
            limit: int = 100,
        ) -> list[object]:
            raise AssertionError("not used")

        async def append_outcome_path_if_missing(
            self,
            *,
            request: object,
            outcome: object,
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
        repository=_FakeRepository(rows=[_row(event_id="event-1")])
    )

    result = await runtime.load_direction_calibration_observations(
        scope=build_monitoring_query_scope(tickers=["AAPL"])
    )

    assert result.row_count == 1
    assert result.usable_row_count == 1
    assert result.observations[0].direction == "bullish"


def test_calibration_facade_exports_builder() -> None:
    builder = build_technical_direction_calibration_observations

    assert callable(builder)
