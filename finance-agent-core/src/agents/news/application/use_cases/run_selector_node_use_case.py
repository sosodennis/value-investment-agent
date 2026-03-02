from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping

from src.agents.news.application.ports import INewsArtifactRepository, LLMLike
from src.agents.news.application.selection_service import run_selector_with_resilience
from src.agents.news.application.state_readers import (
    resolved_ticker_from_state,
    search_artifact_id_from_state,
)
from src.agents.news.application.state_updates import (
    build_selector_node_error_update,
    build_selector_node_update,
)
from src.agents.news.interface.parsers import parse_news_search_result_items
from src.agents.news.interface.prompt_renderers import build_selector_chat_prompt
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)


def _truncate_error_message(message: str, *, limit: int = 320) -> str:
    if len(message) <= limit:
        return message
    return f"{message[:limit]}..."


async def run_selector_node_use_case(
    *,
    state: Mapping[str, object],
    port: INewsArtifactRepository,
    get_llm_fn: Callable[[], LLMLike],
    selector_system_prompt: str,
    selector_user_prompt: str,
) -> WorkflowNodeResult:
    search_artifact_id = search_artifact_id_from_state(state)

    formatted_results = ""
    raw_results: list[JSONObject] = []
    is_degraded = False
    error_msg = ""
    degrade_sources: list[str] = []

    try:
        formatted_results, raw_results = await port.load_search_context(
            search_artifact_id
        )
        parsed_results = parse_news_search_result_items(
            list(raw_results),
            context="news selector search results",
        )
        raw_results = [item.model_dump(mode="json") for item in parsed_results]
    except Exception as exc:
        log_event(
            logger,
            event="news_selector_context_load_failed",
            message="failed to load selector search context",
            level=logging.ERROR,
            error_code="NEWS_SELECTOR_CONTEXT_LOAD_FAILED",
            fields={
                "exception": str(exc),
                "search_artifact_id": search_artifact_id,
            },
        )
        is_degraded = True
        error_msg = f"Failed to load selector context: {str(exc)}"
        degrade_sources.append("context_load")
        return WorkflowNodeResult(
            update=build_selector_node_error_update(error_msg),
            goto="END",
        )

    ticker = resolved_ticker_from_state(state)

    log_event(
        logger,
        event="news_selector_started",
        message="news selector started",
        fields={"ticker": ticker, "raw_result_count": len(raw_results)},
    )
    llm = get_llm_fn()
    prompt = build_selector_chat_prompt(
        system_prompt=selector_system_prompt,
        user_prompt=selector_user_prompt,
    )
    chain = prompt | llm
    selector_result = await run_selector_with_resilience(
        chain=chain,
        ticker=ticker,
        formatted_results=formatted_results,
        raw_results=raw_results,
    )
    selected_indices = selector_result.selected_indices
    if selector_result.is_degraded:
        is_degraded = True
        degrade_sources.append("selector_runtime")
        if error_msg:
            error_msg = f"{error_msg}; {selector_result.error_message}"
        else:
            error_msg = selector_result.error_message

    timestamp = int(time.time())
    selection_artifact_id = None
    try:
        selection_data: JSONObject = {"selected_indices": selected_indices}
        selection_artifact_id = await port.save_news_selection(
            data=selection_data,
            produced_by="financial_news_research.selector_node",
            key_prefix=f"selection_{ticker}_{timestamp}",
        )
    except Exception as exc:
        log_event(
            logger,
            event="news_selector_artifact_save_failed",
            message="failed to save selector artifact",
            level=logging.ERROR,
            error_code="NEWS_SELECTOR_ARTIFACT_SAVE_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )
        return WorkflowNodeResult(
            update=build_selector_node_error_update(
                f"Failed to save selection artifact: {str(exc)}"
            ),
            goto="END",
        )

    log_event(
        logger,
        event="news_selector_completed",
        message="news selector completed",
        fields={
            "ticker": ticker,
            "selected_indices": selected_indices,
            "selected_count": len(selected_indices),
            "is_degraded": is_degraded,
            "degrade_sources": degrade_sources,
        },
    )
    if is_degraded:
        log_event(
            logger,
            event="news_selector_degraded",
            message="news selector degraded and fallback applied",
            level=logging.WARNING,
            error_code="NEWS_SELECTOR_DEGRADED",
            fields={
                "ticker": ticker,
                "search_artifact_id": search_artifact_id,
                "raw_result_count": len(raw_results),
                "selected_count": len(selected_indices),
                "degrade_sources": degrade_sources,
                "degrade_reason": _truncate_error_message(error_msg),
                "fallback_mode": "top_n_indices",
                "fallback_n": min(3, len(raw_results)),
            },
        )

    return WorkflowNodeResult(
        update=build_selector_node_update(
            selection_artifact_id=selection_artifact_id,
            is_degraded=is_degraded,
            error_message=error_msg,
        ),
        goto="fetch_node",
    )
