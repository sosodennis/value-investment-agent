from __future__ import annotations

import pytest

from src.agents.fundamental.domain.valuation.policies.forward_signal_calibration_service import (
    ForwardSignalCalibrationConfig,
)
from src.agents.fundamental.domain.valuation.policies.forward_signal_policy import (
    apply_forward_signal_policy,
    parse_forward_signals,
)


def test_parse_forward_signals_filters_invalid_items() -> None:
    signals = parse_forward_signals(
        [
            {
                "signal_id": "sig-1",
                "source_type": "mda",
                "metric": "growth_outlook",
                "direction": "up",
                "value": 120,
                "unit": "basis_points",
                "confidence": 0.8,
                "evidence": [
                    {
                        "preview_text": "management expects stronger demand",
                        "full_text": "management expects stronger demand",
                        "source_url": "https://example.com/10k",
                    }
                ],
            },
            {
                # invalid: missing confidence
                "signal_id": "sig-2",
                "source_type": "mda",
                "metric": "growth_outlook",
                "direction": "up",
                "value": 50,
                "unit": "basis_points",
                "evidence": [],
            },
        ]
    )

    assert len(signals) == 1
    assert signals[0].signal_id == "sig-1"


def test_apply_forward_signal_policy_accepts_and_bounds_adjustment() -> None:
    signals = parse_forward_signals(
        [
            {
                "signal_id": "sig-1",
                "source_type": "mda",
                "metric": "growth_outlook",
                "direction": "up",
                "value": 500,  # should be clipped by policy max basis points
                "unit": "basis_points",
                "confidence": 0.95,
                "evidence": [
                    {
                        "preview_text": "pipeline growth accelerating",
                        "full_text": "pipeline growth accelerating",
                        "source_url": "https://example.com/10q",
                    }
                ],
            }
        ]
    )

    result = apply_forward_signal_policy(signals)

    assert result.total_count == 1
    assert result.accepted_count == 1
    assert result.rejected_count == 0
    assert result.raw_growth_adjustment_basis_points == pytest.approx(300.0)
    assert result.growth_adjustment_basis_points == pytest.approx(273.0)
    assert result.growth_adjustment == pytest.approx(0.0273)
    assert result.calibration_applied is True
    assert result.mapping_version is not None
    assert result.risk_level == "low"
    assert result.source_types == ("mda",)
    decision = result.decisions[0]
    assert decision.raw_basis_points == pytest.approx(500.0)
    assert decision.calibrated_basis_points == pytest.approx(273.0)
    assert decision.calibration_applied is True
    assert decision.mapping_version == result.mapping_version


def test_apply_forward_signal_policy_marks_low_confidence_high_risk() -> None:
    signals = parse_forward_signals(
        [
            {
                "signal_id": "sig-1",
                "source_type": "news",
                "metric": "margin_outlook",
                "direction": "down",
                "value": 100,
                "unit": "basis_points",
                "confidence": 0.40,
                "evidence": [
                    {
                        "preview_text": "short-term margin pressure",
                        "full_text": "short-term margin pressure",
                        "source_url": "https://example.com/news",
                    }
                ],
            }
        ]
    )

    result = apply_forward_signal_policy(signals)

    assert result.total_count == 1
    assert result.accepted_count == 1
    assert result.raw_margin_adjustment_basis_points < 0
    assert result.margin_adjustment_basis_points < 0
    assert abs(result.margin_adjustment_basis_points) < abs(
        result.raw_margin_adjustment_basis_points
    )
    assert result.risk_level == "high"
    assert result.source_types == ("news",)
    assert result.decisions[0].risk_tag == "low_confidence"


def test_apply_forward_signal_policy_calibration_preserves_direction() -> None:
    signals = parse_forward_signals(
        [
            {
                "signal_id": "sig-up",
                "source_type": "mda",
                "metric": "growth_outlook",
                "direction": "up",
                "value": 180,
                "unit": "basis_points",
                "confidence": 0.8,
                "evidence": [
                    {
                        "preview_text": "demand strong",
                        "full_text": "demand strong",
                        "source_url": "https://example.com/up",
                    }
                ],
            },
            {
                "signal_id": "sig-down",
                "source_type": "xbrl_auto",
                "metric": "margin_outlook",
                "direction": "down",
                "value": 160,
                "unit": "basis_points",
                "confidence": 0.8,
                "evidence": [
                    {
                        "preview_text": "margin pressure",
                        "full_text": "margin pressure",
                        "source_url": "https://example.com/down",
                    }
                ],
            },
        ]
    )

    result = apply_forward_signal_policy(signals)

    assert result.growth_adjustment_basis_points > 0
    assert result.margin_adjustment_basis_points < 0
    growth_decision = next(
        item for item in result.decisions if item.metric == "growth_outlook"
    )
    margin_decision = next(
        item for item in result.decisions if item.metric == "margin_outlook"
    )
    assert growth_decision.raw_basis_points > 0
    assert growth_decision.calibrated_basis_points > 0
    assert margin_decision.raw_basis_points < 0
    assert margin_decision.calibrated_basis_points < 0


def test_apply_forward_signal_policy_supports_custom_calibration_config() -> None:
    signals = parse_forward_signals(
        [
            {
                "signal_id": "sig-custom",
                "source_type": "mda",
                "metric": "growth_outlook",
                "direction": "up",
                "value": 200,
                "unit": "basis_points",
                "confidence": 0.9,
                "evidence": [
                    {
                        "preview_text": "custom config path",
                        "full_text": "custom config path",
                        "source_url": "https://example.com/custom",
                    }
                ],
            }
        ]
    )
    custom_config = ForwardSignalCalibrationConfig(
        mapping_version="custom_v1",
        source_multiplier={"mda": 1.0},
        metric_multiplier={"growth_outlook": 1.0},
        mapping_bins=((400.0, 1.0),),
    )

    result = apply_forward_signal_policy(
        signals,
        calibration_config=custom_config,
    )

    assert result.raw_growth_adjustment_basis_points == pytest.approx(200.0)
    assert result.growth_adjustment_basis_points == pytest.approx(200.0)
    assert result.mapping_version == "custom_v1"


def test_apply_forward_signal_policy_emits_mapping_version_with_empty_signals() -> None:
    result = apply_forward_signal_policy(
        (),
        calibration_config=ForwardSignalCalibrationConfig(
            mapping_version="custom_v1",
            source_multiplier={"mda": 1.0},
            metric_multiplier={"growth_outlook": 1.0},
            mapping_bins=((100.0, 1.0),),
        ),
    )

    assert result.total_count == 0
    assert result.calibration_applied is False
    assert result.mapping_version == "custom_v1"
    assert result.raw_growth_adjustment_basis_points == pytest.approx(0.0)
    assert result.growth_adjustment_basis_points == pytest.approx(0.0)


def test_parse_forward_signals_accepts_xbrl_auto_source() -> None:
    signals = parse_forward_signals(
        [
            {
                "signal_id": "sig-xbrl-auto",
                "source_type": "xbrl_auto",
                "metric": "growth_outlook",
                "direction": "up",
                "value": 80,
                "unit": "basis_points",
                "confidence": 0.7,
                "evidence": [
                    {
                        "preview_text": "xbrl trend acceleration",
                        "full_text": "xbrl trend acceleration",
                        "source_url": "https://www.sec.gov/",
                    }
                ],
            }
        ]
    )

    assert len(signals) == 1
    assert signals[0].source_type == "xbrl_auto"
