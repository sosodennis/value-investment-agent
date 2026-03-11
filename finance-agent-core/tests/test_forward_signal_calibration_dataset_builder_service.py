from __future__ import annotations

import pytest

from src.agents.fundamental.forward_signals.domain.calibration.dataset_builder_service import (
    build_forward_signal_calibration_observations,
    serialize_observations,
)


def test_build_forward_signal_calibration_observations_applies_anchor_gap() -> None:
    replay_results = [
        {
            "ticker": "NVDA",
            "current_price": 100.0,
            "intrinsic_value": 160.0,
            "forward_signal_summary": {
                "raw_growth_adjustment_basis_points": 200.0,
                "raw_margin_adjustment_basis_points": 100.0,
                "source_types": ["mda"],
            },
        }
    ]
    anchors = {"NVDA": 130.0}

    result = build_forward_signal_calibration_observations(
        replay_results=replay_results,
        anchor_target_price_by_ticker=anchors,
        gain=0.5,
        adjustment_cap_basis_points=10_000.0,
    )

    assert result.row_count == 1
    assert result.usable_row_count == 1
    assert result.dropped_row_count == 0
    assert len(result.observations) == 2
    growth = next(
        item for item in result.observations if item.metric == "growth_outlook"
    )
    margin = next(
        item for item in result.observations if item.metric == "margin_outlook"
    )
    assert growth.raw_basis_points == 200.0
    assert margin.raw_basis_points == 100.0
    assert growth.target_basis_points == pytest.approx(-800.0)
    assert margin.target_basis_points == pytest.approx(-400.0)
    assert growth.source_type == "mda"
    assert margin.source_type == "mda"


def test_build_forward_signal_calibration_observations_tracks_drop_reasons() -> None:
    replay_results = [
        {
            "ticker": "AAPL",
            "current_price": 100.0,
            "intrinsic_value": 120.0,
            "forward_signal_summary": {
                "raw_growth_adjustment_basis_points": 100.0,
                "raw_margin_adjustment_basis_points": 50.0,
            },
        },
        {
            "ticker": "MSFT",
            "current_price": 100.0,
            "intrinsic_value": 120.0,
        },
    ]
    anchors = {"AAPL": 110.0}

    result = build_forward_signal_calibration_observations(
        replay_results=replay_results,
        anchor_target_price_by_ticker=anchors,
    )

    assert result.row_count == 2
    assert result.usable_row_count == 1
    assert result.dropped_row_count == 1
    assert result.dropped_reasons == {"missing_anchor_target_price": 1}


def test_serialize_observations_returns_json_payload() -> None:
    replay_results = [
        {
            "ticker": "AAPL",
            "current_price": 100.0,
            "intrinsic_value": 110.0,
            "forward_signal_summary": {
                "growth_adjustment_basis_points": 0.0,
                "margin_adjustment_basis_points": 0.0,
                "source_types": ["xbrl_auto"],
            },
        }
    ]
    anchors = {"AAPL": 105.0}
    built = build_forward_signal_calibration_observations(
        replay_results=replay_results,
        anchor_target_price_by_ticker=anchors,
        gain=1.0,
        adjustment_cap_basis_points=1_000.0,
    )

    serialized = serialize_observations(built.observations)

    assert len(serialized) == 2
    assert serialized[0]["metric"] in {"growth_outlook", "margin_outlook"}
    assert isinstance(serialized[0]["raw_basis_points"], float)
    assert isinstance(serialized[0]["target_basis_points"], float)
