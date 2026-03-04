from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Mapping

from src.agents.news.application.fetch_service import build_cleaned_search_results
from src.agents.news.application.ports import INewsArtifactRepository
from src.agents.news.application.selection_service import format_selector_input
from src.agents.news.application.state_readers import (
    company_name_from_state,
    resolved_ticker_from_state,
)
from src.agents.news.application.state_updates import (
    build_search_node_empty_update,
    build_search_node_error_update,
    build_search_node_no_ticker_update,
    build_search_node_success_update,
)
from src.agents.news.interface.serializers import build_search_progress_preview
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)


async def run_search_node_use_case(
    *,
    state: Mapping[str, object],
    port: INewsArtifactRepository,
    build_output_artifact: Callable[
        [str, JSONObject, str | None], AgentOutputArtifactPayload | None
    ],
    news_search_multi_timeframe_fn: Callable[
        [str, str | None], Awaitable[list[JSONObject]]
    ],
) -> WorkflowNodeResult:
    ticker = resolved_ticker_from_state(state)
    if not ticker:
        log_event(
            logger,
            event="news_search_missing_ticker",
            message="news search skipped due to missing ticker",
            level=logging.WARNING,
            error_code="NEWS_TICKER_MISSING",
        )
        return WorkflowNodeResult(
            update=build_search_node_no_ticker_update(), goto="END"
        )

    log_event(
        logger,
        event="news_search_started",
        message="news search started",
        fields={"ticker": ticker},
    )
    try:
        company_name = company_name_from_state(state)
        results = await news_search_multi_timeframe_fn(ticker, company_name)
    except Exception as exc:
        log_event(
            logger,
            event="news_search_failed",
            message="news search failed",
            level=logging.ERROR,
            error_code="NEWS_SEARCH_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )
        return WorkflowNodeResult(
            update=build_search_node_error_update(str(exc)),
            goto="END",
        )

    result_count = len(results or [])
    log_event(
        logger,
        event="news_search_completed",
        message="news search completed",
        fields={"ticker": ticker, "raw_result_count": result_count},
    )
    if not results:
        return WorkflowNodeResult(update=build_search_node_empty_update(), goto="END")

    cleaned_results = build_cleaned_search_results(results)
    formatted_results = format_selector_input(cleaned_results)

    search_data: JSONObject = {
        "raw_results": cleaned_results,
        "formatted_results": formatted_results,
    }
    timestamp = int(time.time())
    try:
        search_artifact_id = await port.save_search_results(
            data=search_data,
            produced_by="financial_news_research.search_node",
            key_prefix=f"search_{ticker}_{timestamp}",
        )
        log_event(
            logger,
            event="news_search_artifact_saved",
            message="news search artifact saved",
            fields={"ticker": ticker, "search_artifact_id": search_artifact_id},
        )
    except Exception as exc:
        log_event(
            logger,
            event="news_search_artifact_save_failed",
            message="failed to save news search artifact",
            level=logging.ERROR,
            error_code="NEWS_SEARCH_ARTIFACT_SAVE_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )
        return WorkflowNodeResult(
            update=build_search_node_error_update(
                f"Search artifact save failed: {str(exc)}"
            ),
            goto="END",
        )

    preview = build_search_progress_preview(
        article_count=len(cleaned_results),
        cleaned_results=cleaned_results,
    )
    artifact = build_output_artifact(
        f"News Research: Found {len(cleaned_results)} articles for {ticker}",
        preview,
        None,
    )

    return WorkflowNodeResult(
        update=build_search_node_success_update(
            artifact=artifact,
            search_artifact_id=search_artifact_id,
        ),
        goto="selector_node",
    )
