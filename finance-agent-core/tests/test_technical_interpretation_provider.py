from src.agents.technical.application.ports import (
    TechnicalInterpretationInput,
    TechnicalSignalExplainerInput,
)
from src.agents.technical.interface.contracts import AnalystPerspectiveModel
from src.agents.technical.subdomains.interpretation.infrastructure.technical_interpretation_provider import (
    _build_fallback_perspective,
    _finalize_perspective,
)


def _sample_payload() -> TechnicalInterpretationInput:
    return TechnicalInterpretationInput(
        ticker="AAPL",
        direction="BULLISH_EXTENSION",
        risk_level="medium",
        confidence=0.78,
        confidence_calibrated=0.78,
        summary_tags=("trend", "momentum"),
        evidence_items=("Bullish breakout remains intact.",),
        momentum_extremes=None,
        setup_context=None,
        validation_context=None,
        diagnostics_context=None,
        signal_explainer_context=(
            TechnicalSignalExplainerInput(
                signal="FD_OPTIMAL_D",
                plain_name="分數差分強度",
                value_text="0.600",
                timeframe="1d",
                state="NEUTRAL",
                what_it_measures="This estimates how much trend memory needs to be removed to make the series more stable.",
                current_reading_hint="The current reading suggests the market still carries noticeable trend memory or persistence.",
                why_it_matters="It helps explain whether the market data still carries persistent structure instead of behaving like short-lived noise.",
            ),
            TechnicalSignalExplainerInput(
                signal="ADX_14",
                plain_name="趨勢強度",
                value_text="19.650",
                timeframe="1d",
                state="NEUTRAL",
                what_it_measures="This measures how strong the current trend is, without saying whether it is up or down.",
                current_reading_hint="The current reading suggests the market is not in a particularly strong trend.",
                why_it_matters="Stronger trend readings make continuation signals more believable, while weaker readings often mean a choppier market.",
            ),
        ),
    )


def test_build_fallback_perspective_populates_plain_summary_and_explainers() -> None:
    perspective = _build_fallback_perspective(_sample_payload())
    assert perspective.plain_language_summary is not None
    assert "leans bullish" in perspective.plain_language_summary.lower()
    assert perspective.signal_explainers is not None
    assert perspective.signal_explainers[0].signal == "FD_OPTIMAL_D"


def test_finalize_perspective_backfills_missing_humanized_fields() -> None:
    payload = _sample_payload()
    perspective = _finalize_perspective(
        AnalystPerspectiveModel(
            stance="BULLISH_WATCH",
            stance_summary="Bullish watch with medium risk.",
            rationale_summary="Signals remain constructive but still need confirmation.",
        ),
        payload,
    )
    assert perspective.plain_language_summary is not None
    assert "watchlist situation" in perspective.plain_language_summary.lower()
    assert perspective.signal_explainers is not None
    assert len(perspective.signal_explainers) == 2
    assert perspective.signal_explainers[1].what_it_means_now == (
        "The current reading suggests the market is not in a particularly strong trend."
    )
