from __future__ import annotations

from collections.abc import Callable

from src.agents.technical.application.semantic_pipeline_contracts import (
    PriceSeriesDataLike,
    SemanticFinalizeResult,
    TechnicalChartDataLike,
)
from src.agents.technical.application.semantic_policy_input_service import (
    semantic_tags_to_dict,
)
from src.agents.technical.interface.contracts import AnalystPerspectiveModel
from src.agents.technical.subdomains.signal_fusion import SemanticTagPolicyResult
from src.shared.kernel.types import JSONObject


def assemble_semantic_finalize(
    *,
    ticker: str,
    technical_context: JSONObject,
    tags_result: SemanticTagPolicyResult,
    analyst_perspective: AnalystPerspectiveModel,
    price_data: PriceSeriesDataLike | None,
    chart_data: TechnicalChartDataLike | None,
    build_full_report_payload_fn: Callable[..., JSONObject],
) -> SemanticFinalizeResult:
    direction = tags_result.direction.upper()
    opt_d = float(technical_context.get("optimal_d", 0.5))

    raw_data: JSONObject = {}
    if price_data is not None and chart_data is not None:
        raw_data = {
            "price_series": price_data.price_series,
            "fracdiff_series": chart_data.fracdiff_series,
            "z_score_series": chart_data.z_score_series,
        }

    full_report_data_raw = build_full_report_payload_fn(
        ticker=ticker,
        technical_context=technical_context,
        tags_dict=semantic_tags_to_dict(tags_result),
        analyst_perspective=analyst_perspective.model_dump(mode="json"),
        raw_data=raw_data,
    )

    ta_update = {
        "signal": tags_result.direction,
        "statistical_strength": tags_result.statistical_state,
        "risk_level": tags_result.risk_level,
        "analyst_perspective": analyst_perspective.model_dump(mode="json"),
        "semantic_tags": tags_result.tags,
        "memory_strength": tags_result.memory_strength,
    }

    return SemanticFinalizeResult(
        direction=direction,
        opt_d=opt_d,
        raw_data=raw_data,
        full_report_data_raw=full_report_data_raw,
        ta_update=ta_update,
    )
