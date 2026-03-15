from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Protocol

from src.agents.technical.application.ports import (
    ITechnicalInterpretationProvider,
)
from src.agents.technical.application.report_service import (
    build_semantic_report_update,
)
from src.agents.technical.application.semantic_pipeline_service import (
    execute_semantic_pipeline,
)
from src.agents.technical.application.semantic_translate_completion_service import (
    build_semantic_translate_success_result,
)
from src.agents.technical.application.semantic_translate_context_service import (
    resolve_semantic_translate_context,
)
from src.agents.technical.application.state_updates import (
    build_semantic_error_update,
)
from src.agents.technical.subdomains.signal_fusion import (
    SemanticTagPolicyInput,
    SemanticTagPolicyResult,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalVerificationReportArtifactData,
)
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)
TechnicalNodeResult = WorkflowNodeResult


class SemanticTranslateRuntime(Protocol):
    summarize_preview: Callable[[JSONObject], JSONObject]
    build_semantic_output_artifact: Callable[[str, JSONObject, str], dict[str, object]]
    port: _SemanticPort


class _SemanticPort(Protocol):
    async def load_verification_report(
        self,
        artifact_id: str | None,
    ) -> TechnicalVerificationReportArtifactData | None: ...

    async def save_full_report_canonical(
        self,
        data: JSONObject,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...


async def run_semantic_translate_use_case(
    runtime: SemanticTranslateRuntime,
    state: Mapping[str, object],
    *,
    assemble_fn: Callable[[SemanticTagPolicyInput], SemanticTagPolicyResult],
    build_full_report_payload_fn: Callable[..., JSONObject],
    interpretation_provider: ITechnicalInterpretationProvider,
) -> TechnicalNodeResult:
    log_event(
        logger,
        event="technical_semantic_translate_started",
        message="technical semantic translation started",
        fields={"input_count": 0},
    )

    context, context_error = resolve_semantic_translate_context(state)
    if context_error is not None:
        log_event(
            logger,
            event=context_error.event,
            message=context_error.log_message,
            level=logging.ERROR,
            error_code=context_error.error_code,
        )
        log_event(
            logger,
            event="technical_semantic_translate_completed",
            message="technical semantic translation completed",
            level=logging.ERROR,
            fields={
                "status": "error",
                "is_degraded": True,
                "error_code": context_error.error_code,
                "artifact_written": False,
                "input_count": 0,
                "output_count": 0,
            },
        )
        error_update = build_semantic_error_update(context_error.user_message)
        return TechnicalNodeResult(update=error_update.update, goto="END")

    assert context is not None
    try:
        pipeline_result = await execute_semantic_pipeline(
            ticker=context.ticker,
            technical_context=context.technical_context,
            assemble_fn=assemble_fn,
            interpretation_provider=interpretation_provider,
            technical_port=runtime.port,
            verification_report_id=context.verification_report_id,
            build_full_report_payload_fn=build_full_report_payload_fn,
        )
        ta_update = await build_semantic_report_update(
            technical_port=runtime.port,
            ticker=context.ticker,
            technical_context=context.technical_context,
            summarize_preview=runtime.summarize_preview,
            pipeline_result=pipeline_result,
            build_output_artifact=runtime.build_semantic_output_artifact,
        )
        degraded_reasons = list(pipeline_result.degraded_reasons)
        artifact_written = "artifact" in ta_update
        if not artifact_written:
            degraded_reasons.append("TECHNICAL_SEMANTIC_ARTIFACT_FAILED")
        is_degraded = bool(degraded_reasons)
        success_update = build_semantic_translate_success_result(
            ta_update,
            is_degraded=is_degraded,
            degraded_reasons=degraded_reasons,
        )
        if is_degraded:
            log_event(
                logger,
                event="technical_semantic_translate_degraded",
                message="technical semantic translation completed with degraded quality",
                level=logging.WARNING,
                error_code="TECHNICAL_SEMANTIC_TRANSLATE_DEGRADED",
                fields={
                    "ticker": context.ticker,
                    "degrade_source": "semantic_pipeline",
                    "fallback_mode": "continue_with_partial_semantic_output",
                    "degraded_reasons": degraded_reasons,
                    "input_count": len(pipeline_result.tags_result.tags),
                    "output_count": len(ta_update),
                },
            )
        log_event(
            logger,
            event="technical_semantic_translate_completed",
            message="technical semantic translation completed",
            level=logging.WARNING if is_degraded else logging.INFO,
            fields={
                "ticker": context.ticker,
                "status": "done",
                "is_degraded": is_degraded,
                "artifact_written": artifact_written,
                "semantic_tag_count": len(pipeline_result.tags_result.tags),
                "degraded_reason_count": len(degraded_reasons),
                "degraded_reasons": degraded_reasons,
                "input_count": len(pipeline_result.tags_result.tags),
                "output_count": len(ta_update),
            },
        )
        return TechnicalNodeResult(update=success_update.update, goto="END")
    except Exception as exc:
        log_event(
            logger,
            event="technical_semantic_translate_failed",
            message="technical semantic translation failed",
            level=logging.ERROR,
            error_code="TECHNICAL_SEMANTIC_TRANSLATION_FAILED",
            fields={"ticker": context.ticker, "exception": str(exc)},
        )
        log_event(
            logger,
            event="technical_semantic_translate_completed",
            message="technical semantic translation completed",
            level=logging.ERROR,
            fields={
                "ticker": context.ticker,
                "status": "error",
                "is_degraded": True,
                "error_code": "TECHNICAL_SEMANTIC_TRANSLATION_FAILED",
                "artifact_written": False,
                "input_count": 1,
                "output_count": 0,
            },
        )
        error_update = build_semantic_error_update(
            f"Semantic translation failed: {str(exc)}"
        )
        return TechnicalNodeResult(update=error_update.update, goto="END")
