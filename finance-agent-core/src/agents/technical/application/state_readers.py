from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class TechnicalStateContext:
    price_artifact_id: str | None
    chart_data_id: str | None
    optimal_d: object
    z_score_latest: object


def resolved_ticker_from_state(state: Mapping[str, object]) -> str | None:
    intent_ctx_raw = state.get("intent_extraction", {})
    intent_ctx = intent_ctx_raw if isinstance(intent_ctx_raw, Mapping) else {}
    resolved_ticker = intent_ctx.get("resolved_ticker")
    if not isinstance(resolved_ticker, str):
        return None
    resolved_ticker = resolved_ticker.strip()
    return resolved_ticker or None


def technical_state_from_state(state: Mapping[str, object]) -> TechnicalStateContext:
    technical_ctx_raw = state.get("technical_analysis", {})
    technical_ctx = technical_ctx_raw if isinstance(technical_ctx_raw, Mapping) else {}
    price_artifact_id_raw = technical_ctx.get("price_artifact_id")
    chart_data_id_raw = technical_ctx.get("chart_data_id")
    return TechnicalStateContext(
        price_artifact_id=(
            price_artifact_id_raw if isinstance(price_artifact_id_raw, str) else None
        ),
        chart_data_id=chart_data_id_raw if isinstance(chart_data_id_raw, str) else None,
        optimal_d=technical_ctx.get("optimal_d"),
        z_score_latest=technical_ctx.get("z_score_latest"),
    )
