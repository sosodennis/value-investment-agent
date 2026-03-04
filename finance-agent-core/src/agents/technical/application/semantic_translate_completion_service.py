from __future__ import annotations

from langchain_core.messages import AIMessage

from src.agents.technical.application.state_updates import (
    SemanticCommandUpdateResult,
    build_semantic_success_update,
)
from src.shared.kernel.types import JSONObject


def build_semantic_translate_success_result(
    ta_update: JSONObject,
    *,
    is_degraded: bool,
    degraded_reasons: list[str],
) -> SemanticCommandUpdateResult:
    success_update = build_semantic_success_update(
        ta_update,
        is_degraded=is_degraded,
        degraded_reasons=degraded_reasons,
    )
    success_update.update["messages"] = [
        AIMessage(
            content="",
            additional_kwargs={
                "type": "technical_analysis",
                "agent_id": "technical_analysis",
                "status": "done",
            },
        )
    ]
    return success_update
