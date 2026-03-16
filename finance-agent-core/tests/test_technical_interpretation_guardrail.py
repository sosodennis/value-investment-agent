from src.agents.technical.subdomains.interpretation.domain.interpretation_guardrail_service import (
    apply_interpretation_guardrail,
)


def test_guardrail_allows_aligned_bullish() -> None:
    outcome = apply_interpretation_guardrail(
        direction="BULLISH_EXTENSION",
        risk_level="low",
        interpretation="Bullish momentum persists across timeframes.",
    )
    assert outcome.is_aligned is True
    assert outcome.content == "Bullish momentum persists across timeframes."


def test_guardrail_blocks_mismatch() -> None:
    outcome = apply_interpretation_guardrail(
        direction="BULLISH_EXTENSION",
        risk_level="medium",
        interpretation="Bearish breakdown continues with weak follow-through.",
    )
    assert outcome.is_aligned is False
    assert "bullish" in outcome.content.lower()
