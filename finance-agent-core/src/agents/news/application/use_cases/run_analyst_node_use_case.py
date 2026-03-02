from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping

from pydantic import BaseModel

from src.agents.news.application.analysis_service import (
    analyze_news_items,
    build_analysis_chains,
)
from src.agents.news.application.ports import (
    FinbertAnalyzerLike,
    INewsArtifactRepository,
    LLMLike,
)
from src.agents.news.application.state_readers import (
    news_items_artifact_id_from_state,
    resolved_ticker_from_state,
)
from src.agents.news.application.state_updates import (
    build_analyst_chain_error_update,
    build_analyst_node_error_update,
    build_analyst_node_update,
)
from src.agents.news.interface.parsers import parse_news_items
from src.agents.news.interface.prompt_renderers import build_analyst_chat_prompts
from src.shared.kernel.tools.logger import get_logger, log_event
from src.shared.kernel.types import JSONObject
from src.shared.kernel.workflow_contracts import WorkflowNodeResult

logger = get_logger(__name__)


def _truncate_error_message(message: str, *, limit: int = 320) -> str:
    if len(message) <= limit:
        return message
    return f"{message[:limit]}..."


def _append_source_once(sources: list[str], source: str) -> None:
    if source not in sources:
        sources.append(source)


async def run_analyst_node_use_case(
    *,
    state: Mapping[str, object],
    port: INewsArtifactRepository,
    get_llm_fn: Callable[[], LLMLike],
    get_finbert_analyzer_fn: Callable[[], FinbertAnalyzerLike],
    analyst_system_prompt: str,
    analyst_user_prompt_basic: str,
    analyst_user_prompt_with_finbert: str,
    analysis_model_type: type[BaseModel],
) -> WorkflowNodeResult:
    news_items_id = news_items_artifact_id_from_state(state)

    news_items: list[JSONObject] = []
    article_errors: list[str] = []
    degrade_sources: list[str] = []
    try:
        news_items = await port.load_news_items_data(news_items_id)
        parsed_news_items = parse_news_items(
            list(news_items),
            context="news analyst items",
        )
        news_items = [item.model_dump(mode="json") for item in parsed_news_items]
    except Exception as exc:
        log_event(
            logger,
            event="news_analyst_items_load_failed",
            message="failed to load news items for analyst",
            level=logging.ERROR,
            error_code="NEWS_ANALYST_ITEMS_LOAD_FAILED",
            fields={"news_items_artifact_id": news_items_id, "exception": str(exc)},
        )
        return WorkflowNodeResult(
            update=build_analyst_node_error_update(
                f"Failed to retrieve news items: {str(exc)}"
            ),
            goto="END",
        )

    ticker = resolved_ticker_from_state(state)

    log_event(
        logger,
        event="news_analyst_started",
        message="news analyst started",
        fields={"ticker": ticker, "article_count": len(news_items)},
    )

    finbert_analyzer = get_finbert_analyzer_fn()
    llm = get_llm_fn()

    prompt_basic, prompt_finbert = build_analyst_chat_prompts(
        system_prompt=analyst_system_prompt,
        user_prompt_basic=analyst_user_prompt_basic,
        user_prompt_with_finbert=analyst_user_prompt_with_finbert,
    )

    try:
        analysis_chains = build_analysis_chains(
            llm=llm,
            prompt_basic=prompt_basic,
            prompt_finbert=prompt_finbert,
            analysis_model_type=analysis_model_type,
        )
    except Exception as exc:
        log_event(
            logger,
            event="news_analyst_chain_build_failed",
            message="failed to build analyst chains",
            level=logging.ERROR,
            error_code="NEWS_ANALYST_CHAIN_BUILD_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )
        return WorkflowNodeResult(
            update=build_analyst_chain_error_update(str(exc)),
            goto="END",
        )

    analyst_result = await analyze_news_items(
        news_items=news_items,
        ticker=ticker,
        port=port,
        finbert_analyzer=finbert_analyzer,
        chains=analysis_chains,
    )
    news_items = analyst_result.news_items
    if analyst_result.article_errors:
        _append_source_once(degrade_sources, "analysis_items")
        article_errors.extend(analyst_result.article_errors)

    timestamp = int(time.time())
    try:
        news_items_id = await port.save_news_items(
            data={"news_items": news_items},
            produced_by="financial_news_research.analyst_node",
            key_prefix=f"news_items_analyzed_{ticker}_{timestamp}",
        )
    except Exception as exc:
        log_event(
            logger,
            event="news_analyst_artifact_save_failed",
            message="failed to save analyzed news items artifact",
            level=logging.ERROR,
            error_code="NEWS_ANALYST_ARTIFACT_SAVE_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )
        news_items_id = None
        article_errors.append(
            f"Failed to save analyzed news items artifact: {str(exc)}"
        )
        _append_source_once(degrade_sources, "artifact_save")

    is_degraded = bool(article_errors)
    log_event(
        logger,
        event="news_analyst_completed",
        message="news analyst completed",
        fields={
            "ticker": ticker,
            "article_count": len(news_items),
            "article_errors_count": len(article_errors),
            "is_degraded": is_degraded,
            "degrade_sources": degrade_sources,
            "news_items_artifact_id": news_items_id,
        },
    )
    if is_degraded:
        log_event(
            logger,
            event="news_analyst_degraded",
            message="news analyst degraded with partial failures",
            level=logging.WARNING,
            error_code="NEWS_ANALYST_DEGRADED",
            fields={
                "ticker": ticker,
                "news_items_artifact_id": news_items_id,
                "article_count": len(news_items),
                "article_errors_count": len(article_errors),
                "degrade_sources": degrade_sources,
                "degrade_reason": _truncate_error_message(article_errors[0]),
            },
        )

    return WorkflowNodeResult(
        update=build_analyst_node_update(
            news_items_id=news_items_id, article_errors=article_errors
        ),
        goto="aggregator_node",
    )
