from src.agents.technical.subdomains.interpretation.domain import (
    apply_interpretation_guardrail,
)
from src.shared.artifacts.technical_contracts import (
    AnalystPerspectiveEvidenceItemModel,
    AnalystPerspectiveModel,
    AnalystPerspectiveSignalExplainerModel,
)


def test_guardrail_preserves_aligned_perspective_and_trims_collections() -> None:
    perspective = AnalystPerspectiveModel(
        stance="BULLISH_WATCH",
        stance_summary="Bullish watch with low risk.",
        rationale_summary="Bullish momentum persists across timeframes.",
        plain_language_summary="The setup leans bullish, but it still needs confirmation.",
        signal_explainers=[
            AnalystPerspectiveSignalExplainerModel(
                signal=f"S{index}",
                plain_name=f"Signal {index}",
                what_it_means_now="Mixed reading.",
                why_it_matters_now="It affects confidence.",
            )
            for index in range(4)
        ],
        top_evidence=[
            AnalystPerspectiveEvidenceItemModel(
                label=f"E{index}",
                rationale="Mixed evidence.",
            )
            for index in range(4)
        ],
    )

    outcome = apply_interpretation_guardrail(
        direction="BULLISH_EXTENSION",
        risk_level="low",
        perspective=perspective,
    )

    assert outcome.is_aligned is True
    assert outcome.violation_reason is None
    assert outcome.perspective.plain_language_summary == (
        "The setup leans bullish, but it still needs confirmation."
    )
    assert outcome.perspective.signal_explainers is not None
    assert len(outcome.perspective.signal_explainers) == 3
    assert outcome.perspective.top_evidence is not None
    assert len(outcome.perspective.top_evidence) == 3


def test_guardrail_replaces_empty_summary_with_expected_direction_fallback() -> None:
    outcome = apply_interpretation_guardrail(
        direction="BEARISH_BREAKDOWN",
        risk_level="high",
        perspective=AnalystPerspectiveModel(
            stance="BEARISH_WATCH",
            stance_summary="Bearish watch with high risk.",
            rationale_summary="  ",
        ),
    )

    assert outcome.is_aligned is False
    assert outcome.detected_direction is None
    assert outcome.violation_reason == "interpretation_empty"
    assert outcome.perspective.stance == "BEARISH_WATCH"
    assert outcome.perspective.stance_summary == "Bearish Watch with high risk."


def test_guardrail_replaces_direction_mismatch_with_deterministic_fallback() -> None:
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
    assert outcome.detected_direction == "bearish"
    assert outcome.violation_reason == (
        "direction_mismatch:expected=bullish,detected=bearish"
    )
    assert outcome.perspective.stance == "BULLISH_WATCH"
    assert "deterministic signal" in outcome.perspective.plain_language_summary.lower()


def test_guardrail_accepts_perspective_without_direction_hints() -> None:
    outcome = apply_interpretation_guardrail(
        direction="BULLISH_EXTENSION",
        risk_level="medium",
        perspective=AnalystPerspectiveModel(
            stance="MOMENTUM_SHIFT",
            stance_summary="A momentum shift is developing.",
            rationale_summary="The signal set shows a mixed transition.",
        ),
    )

    assert outcome.is_aligned is True
    assert outcome.detected_direction is None
    assert outcome.violation_reason is None
    assert outcome.perspective.stance == "MOMENTUM_SHIFT"
