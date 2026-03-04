from __future__ import annotations

from collections.abc import Callable

from src.agents.technical.application.ports import (
    ITechnicalBacktestRuntime,
    ITechnicalFracdiffRuntime,
    ITechnicalInterpretationProvider,
    ITechnicalMarketDataProvider,
)
from src.agents.technical.application.semantic_backtest_context_service import (
    assemble_backtest_context,
)
from src.agents.technical.application.semantic_finalize_service import (
    assemble_semantic_finalize,
)
from src.agents.technical.application.semantic_pipeline_contracts import (
    SemanticPipelineResult,
    TechnicalPortLike,
)
from src.agents.technical.application.semantic_policy_input_service import (
    build_semantic_policy_input,
    semantic_tags_to_dict,
)
from src.agents.technical.domain.signal_policy import (
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from src.shared.kernel.types import JSONObject


async def execute_semantic_pipeline(
    *,
    ticker: str,
    technical_context: JSONObject,
    assemble_fn: Callable[[SemanticTagPolicyInput], SemanticTagPolicyResult],
    interpretation_provider: ITechnicalInterpretationProvider,
    fracdiff_runtime: ITechnicalFracdiffRuntime,
    market_data_provider: ITechnicalMarketDataProvider,
    backtest_runtime: ITechnicalBacktestRuntime,
    technical_port: TechnicalPortLike,
    price_artifact_id: str | None,
    chart_artifact_id: str | None,
    build_full_report_payload_fn: Callable[..., JSONObject],
) -> SemanticPipelineResult:
    tags_result = assemble_fn(build_semantic_policy_input(technical_context))

    backtest_context_result = await assemble_backtest_context(
        technical_port=technical_port,
        price_artifact_id=price_artifact_id,
        chart_artifact_id=chart_artifact_id,
        fracdiff_runtime=fracdiff_runtime,
        market_data_provider=market_data_provider,
        backtest_runtime=backtest_runtime,
    )

    interpretation_result = await interpretation_provider.generate_interpretation(
        semantic_tags_to_dict(tags_result),
        ticker,
        backtest_context_result.backtest_context,
        backtest_context_result.wfa_context,
    )

    semantic_finalize_result = assemble_semantic_finalize(
        ticker=ticker,
        technical_context=technical_context,
        tags_result=tags_result,
        llm_interpretation=interpretation_result.content,
        price_data=backtest_context_result.price_data,
        chart_data=backtest_context_result.chart_data,
        build_full_report_payload_fn=build_full_report_payload_fn,
    )

    degraded_reasons: list[str] = []
    if backtest_context_result.is_degraded:
        degraded_reasons.append(
            backtest_context_result.failure_code
            or "TECHNICAL_SEMANTIC_BACKTEST_CONTEXT_FAILED"
        )
    if interpretation_result.is_fallback:
        degraded_reasons.append(
            interpretation_result.failure.failure_code
            if interpretation_result.failure is not None
            else "TECHNICAL_LLM_INTERPRETATION_FAILED"
        )

    return SemanticPipelineResult(
        tags_result=tags_result,
        llm_interpretation=interpretation_result.content,
        backtest_context_result=backtest_context_result,
        semantic_finalize_result=semantic_finalize_result,
        llm_is_fallback=interpretation_result.is_fallback,
        llm_failure_code=(
            interpretation_result.failure.failure_code
            if interpretation_result.failure is not None
            else None
        ),
        is_degraded=bool(degraded_reasons),
        degraded_reasons=tuple(degraded_reasons),
    )
