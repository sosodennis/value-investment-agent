from __future__ import annotations

import pytest

from src.agents.fundamental.domain.valuation.assumptions import (
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
    assert result.growth_adjustment_basis_points == pytest.approx(300.0)
    assert result.growth_adjustment == pytest.approx(0.03)
    assert result.risk_level == "low"
    assert result.source_types == ("mda",)


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
    assert result.margin_adjustment_basis_points < 0
    assert result.risk_level == "high"
    assert result.source_types == ("news",)
    assert result.decisions[0].risk_tag == "low_confidence"
