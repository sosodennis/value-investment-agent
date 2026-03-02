from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.agents.technical.application.state_readers import (
    resolved_ticker_from_state,
    technical_state_from_state,
)
from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class SemanticTranslateContext:
    ticker: str
    technical_context: JSONObject
    price_artifact_id: str | None
    chart_artifact_id: str | None


@dataclass(frozen=True)
class SemanticTranslateContextError:
    event: str
    log_message: str
    error_code: str
    user_message: str


def resolve_semantic_translate_context(
    state: Mapping[str, object],
) -> tuple[SemanticTranslateContext | None, SemanticTranslateContextError | None]:
    ctx_raw = state.get("technical_analysis", {})
    ctx = ctx_raw if isinstance(ctx_raw, Mapping) else {}

    ticker = resolved_ticker_from_state(state)
    if ticker is None:
        return None, SemanticTranslateContextError(
            event="technical_semantic_translate_missing_ticker",
            log_message="technical semantic translation failed due to missing ticker",
            error_code="TECHNICAL_SEMANTIC_TICKER_MISSING",
            user_message="Missing intent_extraction.resolved_ticker",
        )

    technical_state = technical_state_from_state(state)
    if technical_state.optimal_d is None or technical_state.z_score_latest is None:
        return None, SemanticTranslateContextError(
            event="technical_semantic_translate_missing_metrics",
            log_message="technical semantic translation failed due to missing fracdiff metrics",
            error_code="TECHNICAL_SEMANTIC_METRICS_MISSING",
            user_message="No FracDiff metrics available for translation",
        )

    return (
        SemanticTranslateContext(
            ticker=ticker,
            technical_context=dict(ctx),
            price_artifact_id=technical_state.price_artifact_id,
            chart_artifact_id=technical_state.chart_data_id,
        ),
        None,
    )
