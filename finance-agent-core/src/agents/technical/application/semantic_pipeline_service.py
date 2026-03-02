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

    llm_interpretation = await interpretation_provider.generate_interpretation(
        semantic_tags_to_dict(tags_result),
        ticker,
        backtest_context_result.backtest_context,
        backtest_context_result.wfa_context,
    )

    semantic_finalize_result = assemble_semantic_finalize(
        ticker=ticker,
        technical_context=technical_context,
        tags_result=tags_result,
        llm_interpretation=llm_interpretation,
        price_data=backtest_context_result.price_data,
        chart_data=backtest_context_result.chart_data,
        build_full_report_payload_fn=build_full_report_payload_fn,
    )

    return SemanticPipelineResult(
        tags_result=tags_result,
        llm_interpretation=llm_interpretation,
        backtest_context_result=backtest_context_result,
        semantic_finalize_result=semantic_finalize_result,
    )
