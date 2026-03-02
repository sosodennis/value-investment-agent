from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class TechnicalStateContext:
    price_artifact_id: str | None
    chart_data_id: str | None
    optimal_d: float | None
    z_score_latest: float | None


def _read_non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_optional_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def resolved_ticker_from_state(state: Mapping[str, object]) -> str | None:
    intent_ctx_raw = state.get("intent_extraction", {})
    intent_ctx = intent_ctx_raw if isinstance(intent_ctx_raw, Mapping) else {}
    return _read_non_empty_string(intent_ctx.get("resolved_ticker"))


def technical_state_from_state(state: Mapping[str, object]) -> TechnicalStateContext:
    technical_ctx_raw = state.get("technical_analysis", {})
    technical_ctx = technical_ctx_raw if isinstance(technical_ctx_raw, Mapping) else {}
    return TechnicalStateContext(
        price_artifact_id=_read_non_empty_string(
            technical_ctx.get("price_artifact_id")
        ),
        chart_data_id=_read_non_empty_string(technical_ctx.get("chart_data_id")),
        optimal_d=_read_optional_number(technical_ctx.get("optimal_d")),
        z_score_latest=_read_optional_number(technical_ctx.get("z_score_latest")),
    )
