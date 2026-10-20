from datetime import datetime

from src.agents.technical.subdomains.calibration import (
    TechnicalDirectionCalibrationObservation,
)
from src.agents.technical.subdomains.decision_observability.public import (
    TechnicalMonitoringReadModelRow,
    build_technical_direction_calibration_observations,
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


def test_builder_maps_valid_rows_and_reports_dropped_rows() -> None:
    result = build_technical_direction_calibration_observations(
        [
            _row(event_id="valid"),
            _row(event_id="missing-outcome", outcome_path_id=None),
            _row(event_id="unsupported-direction", direction="NEUTRAL_CONSOLIDATION"),
        ]
    )

    assert result.observations == (
        TechnicalDirectionCalibrationObservation(
            timeframe="1d",
            horizon="5d",
            raw_score=0.8,
            direction="bullish",
            target_outcome=0.04,
        ),
    )
    assert result.row_count == 3
    assert result.usable_row_count == 1
    assert result.dropped_row_count == 2
    assert result.dropped_reasons == {
        "missing_outcome_path": 1,
        "unsupported_direction_family": 1,
    }
