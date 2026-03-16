from __future__ import annotations

import logging
from collections.abc import Callable

from src.agents.technical.application.ports import (
    ITechnicalInterpretationProvider,
    TechnicalInterpretationResult,
    TechnicalProviderFailure,
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
from src.agents.technical.application.semantic_verification_context_service import (
    assemble_verification_context,
)
from src.agents.technical.subdomains.interpretation.domain import (
    apply_interpretation_guardrail,
)
from src.agents.technical.subdomains.signal_fusion import (
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject

logger = get_logger(__name__)


async def execute_semantic_pipeline(
    *,
    ticker: str,
    technical_context: JSONObject,
    assemble_fn: Callable[[SemanticTagPolicyInput], SemanticTagPolicyResult],
    interpretation_provider: ITechnicalInterpretationProvider,
    technical_port: TechnicalPortLike,
    verification_report_id: str | None,
    build_full_report_payload_fn: Callable[..., JSONObject],
) -> SemanticPipelineResult:
    tags_result = assemble_fn(build_semantic_policy_input(technical_context))

    backtest_context_result = await assemble_verification_context(
        technical_port=technical_port,
        verification_report_id=verification_report_id,
    )

    interpretation_result = await interpretation_provider.generate_interpretation(
        semantic_tags_to_dict(tags_result),
        ticker,
        backtest_context_result.backtest_context,
        backtest_context_result.wfa_context,
    )

    if not interpretation_result.is_fallback:
        guardrail_outcome = apply_interpretation_guardrail(
            direction=tags_result.direction,
            risk_level=tags_result.risk_level,
            interpretation=interpretation_result.content,
        )
        if not guardrail_outcome.is_aligned:
            log_event(
                logger,
                event="technical_llm_guardrail_triggered",
                message="technical llm guardrail replaced interpretation",
                level=logging.WARNING,
                error_code="TECHNICAL_LLM_GUARDRAIL_MISMATCH",
                fields={
                    "ticker": ticker,
                    "expected_direction": tags_result.direction,
                    "detected_direction": guardrail_outcome.detected_direction,
                    "guardrail_version": guardrail_outcome.guardrail_version,
                    "violation_reason": guardrail_outcome.violation_reason,
                },
            )
            interpretation_result = TechnicalInterpretationResult(
                content=guardrail_outcome.content,
                is_fallback=True,
                failure=TechnicalProviderFailure(
                    failure_code="TECHNICAL_LLM_GUARDRAIL_MISMATCH",
                    reason=guardrail_outcome.violation_reason,
                ),
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
            or "TECHNICAL_VERIFICATION_CONTEXT_FAILED"
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
