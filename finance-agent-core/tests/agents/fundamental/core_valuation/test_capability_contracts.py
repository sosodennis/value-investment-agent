from __future__ import annotations

import pytest

from src.agents.fundamental.subdomains.core_valuation.domain.parameterization.forward_signal_adjustment_service import (
    apply_forward_signal_adjustments,
)
from src.agents.fundamental.subdomains.core_valuation.domain.parameterization.forward_signal_parser_service import (
    parse_market_forward_signals,
)
from src.agents.fundamental.subdomains.core_valuation.interface.replay_contracts import (
    parse_valuation_replay_input_model,
)


def _signal(*, direction: str = "up", value: float = 100.0) -> dict[str, object]:
    return {
        "signal_id": "growth-1",
        "source_type": "mda",
        "metric": "growth_outlook",
        "direction": direction,
        "value": value,
        "unit": "basis_points",
        "confidence": 0.9,
        "as_of": "2026-01-01",
        "evidence": [
            {
                "preview_text": "Management expects growth.",
                "full_text": "Management expects growth to continue.",
                "source_url": "https://example.test/filing",
            }
        ],
    }


def test_market_signal_parser_normalizes_and_discards_invalid_payloads() -> None:
    parsed = parse_market_forward_signals(
        [_signal(), {"metric": "unsupported"}, object()]
    )

    assert len(parsed) == 1
    assert parsed[0].signal_id == "growth-1"
    assert parsed[0].metric == "growth_outlook"
    assert parsed[0].value == 100.0


def test_forward_signal_adjustments_preserve_deterministic_calibrated_behavior() -> (
    None
):
    outcome = apply_forward_signal_adjustments(
        params={"growth_rates": [0.1, 0.2], "operating_margins": [0.2]},
        assumptions=[],
        metadata={},
        model_type="dcf_standard",
        raw_signals=[_signal()],
    )

    assert outcome.params["growth_rates"] == pytest.approx([0.109, 0.209])
    assert outcome.params["operating_margins"] == [0.2]
    assert outcome.log_fields is not None
    assert outcome.log_fields["signals_accepted"] == 1
    assert outcome.log_fields["growth_applied"] is True
    assert outcome.metadata["forward_signal"]["mapping_version"]


def test_replay_contract_accepts_public_financial_and_signal_payloads() -> None:
    replay_input = parse_valuation_replay_input_model(
        {
            "schema_version": "valuation_replay_input_v2",
            "model_type": "dcf_standard",
            "ticker": "ABC",
            "reports": [{"base": {}, "industry_type": "General"}],
            "forward_signals": [_signal()],
        },
        context="test replay",
    )

    assert replay_input.reports[0].industry_type == "General"
    assert replay_input.forward_signals is not None
    assert replay_input.forward_signals[0].signal_id == "growth-1"
