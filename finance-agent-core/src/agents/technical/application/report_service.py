from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from src.agents.technical.application.semantic_service import (
    SemanticPipelineResult,
    semantic_tags_to_dict,
)
from src.shared.kernel.tools.logger import get_logger
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject

logger = get_logger(__name__)


class _TechnicalReportPort(Protocol):
    async def save_full_report_canonical(
        self,
        data: object,
        *,
        produced_by: str,
        key_prefix: str | None = None,
    ) -> str: ...


def _fallback_ta_update(
    *, tags_dict: JSONObject, llm_interpretation: str
) -> JSONObject:
    return {
        "signal": tags_dict["direction"],
        "statistical_strength": tags_dict["statistical_state"],
        "risk_level": tags_dict["risk_level"],
        "llm_interpretation": llm_interpretation,
        "semantic_tags": tags_dict["tags"],
        "memory_strength": tags_dict["memory_strength"],
    }


async def build_semantic_report_update(
    *,
    technical_port: _TechnicalReportPort,
    ticker: str,
    technical_context: JSONObject,
    summarize_preview: Callable[[JSONObject], JSONObject],
    pipeline_result: SemanticPipelineResult,
    build_output_artifact: Callable[[str, JSONObject, str], AgentOutputArtifactPayload],
) -> JSONObject:
    try:
        preview = summarize_preview(technical_context)
        report_id = await technical_port.save_full_report_canonical(
            data=pipeline_result.semantic_finalize_result.full_report_data_raw,
            produced_by="technical_analysis.semantic_translate",
            key_prefix=f"ta_{ticker}_{int(time.time())}",
        )
        artifact = build_output_artifact(
            (
                f"Technical Analysis: {pipeline_result.semantic_finalize_result.direction} "
                f"(d={pipeline_result.semantic_finalize_result.opt_d:.2f})"
            ),
            preview,
            report_id,
        )
        ta_update = dict(pipeline_result.semantic_finalize_result.ta_update)
        ta_update["artifact"] = artifact
        return ta_update
    except Exception as exc:
        logger.error(f"Failed to generate artifact in node: {exc}")
        tags_dict = semantic_tags_to_dict(pipeline_result.tags_result)
        return _fallback_ta_update(
            tags_dict=tags_dict,
            llm_interpretation=pipeline_result.llm_interpretation,
        )
