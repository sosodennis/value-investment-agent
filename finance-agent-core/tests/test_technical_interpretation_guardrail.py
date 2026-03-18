from src.agents.technical.interface.contracts import (
    AnalystPerspectiveEvidenceItemModel,
    AnalystPerspectiveModel,
    AnalystPerspectiveSignalExplainerModel,
)
from src.agents.technical.subdomains.interpretation.domain.interpretation_guardrail_service import (
    apply_interpretation_guardrail,
)


def test_guardrail_allows_aligned_bullish_and_preserves_plain_summary() -> None:
    outcome = apply_interpretation_guardrail(
        direction="BULLISH_EXTENSION",
        risk_level="low",
        perspective=AnalystPerspectiveModel(
            stance="BULLISH_WATCH",
            stance_summary="Bullish watch with low risk.",
            rationale_summary="Bullish momentum persists across timeframes.",
            plain_language_summary="The setup leans bullish, but it still needs confirmation.",
        ),
    )
    assert outcome.is_aligned is True
    assert outcome.perspective.plain_language_summary == (
        "The setup leans bullish, but it still needs confirmation."
    )


def test_guardrail_blocks_direction_mismatch_with_fallback_summary() -> None:
    outcome = apply_interpretation_guardrail(
        direction="BULLISH_EXTENSION",
        risk_level="medium",
        perspective=AnalystPerspectiveModel(
            stance="BEARISH_WATCH",
            stance_summary="Bearish watch with medium risk.",
            rationale_summary="Bearish breakdown continues with weak follow-through.",
        ),
    )
    assert outcome.is_aligned is False
    assert outcome.perspective.stance == "BULLISH_WATCH"
    assert "deterministic signal" in outcome.perspective.plain_language_summary.lower()


def test_guardrail_trims_explainer_and_evidence_lists() -> None:
    perspective = AnalystPerspectiveModel(
        stance="NEUTRAL",
        stance_summary="Neutral with medium risk.",
        rationale_summary="Signals are mixed across the stack.",
        signal_explainers=[
            AnalystPerspectiveSignalExplainerModel(
                signal=f"S{i}",
                plain_name=f"Signal {i}",
                what_it_means_now="Mixed reading.",
                why_it_matters_now="It affects confidence.",
            )
            for i in range(4)
        ],
        top_evidence=[
            AnalystPerspectiveEvidenceItemModel(
                label=f"E{i}",
                rationale="Mixed evidence.",
            )
            for i in range(4)
        ],
    )
    outcome = apply_interpretation_guardrail(
        direction="NEUTRAL",
        risk_level="medium",
        perspective=perspective,
    )
    assert outcome.is_aligned is True
    assert (
        outcome.perspective.plain_language_summary
        == "Signals are mixed across the stack."
    )
    assert outcome.perspective.signal_explainers is not None
    assert len(outcome.perspective.signal_explainers) == 3
    assert outcome.perspective.top_evidence is not None
    assert len(outcome.perspective.top_evidence) == 3
