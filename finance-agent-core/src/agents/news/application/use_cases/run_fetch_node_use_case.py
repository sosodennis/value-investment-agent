from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Mapping

from src.agents.news.application.fetch_service import (
    build_articles_to_fetch,
    build_news_items_from_fetch_results,
)
from src.agents.news.application.ports import (
    FetchContentResult,
    INewsArtifactRepository,
    NewsItemFactoryLike,
    SourceFactoryLike,
)
from src.agents.news.application.state_readers import (
    resolved_ticker_from_state,
    search_artifact_id_from_state,
    selection_artifact_id_from_state,
)
from src.agents.news.application.state_updates import (
    build_fetch_node_error_update,
    build_fetch_node_update,
)
from src.agents.news.interface.parsers import parse_news_search_result_items
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


async def run_fetch_node_use_case(
    *,
    state: Mapping[str, object],
    port: INewsArtifactRepository,
    fetch_clean_text_async_fn: Callable[[str], Awaitable[FetchContentResult]],
    generate_news_id_fn: Callable[[str | None, str | None], str],
    get_source_reliability_fn: Callable[[str], float],
    item_factory: NewsItemFactoryLike,
    source_factory: SourceFactoryLike,
) -> WorkflowNodeResult:
    search_id = search_artifact_id_from_state(state)
    selection_id = selection_artifact_id_from_state(state)

    raw_results: list[JSONObject] = []
    selected_indices: list[int] = []
    article_errors: list[str] = []
    degrade_sources: list[str] = []

    try:
        raw_results, selected_indices = await port.load_fetch_context(
            search_id, selection_id
        )
    except Exception as exc:
        log_event(
            logger,
            event="news_fetch_context_load_failed",
            message="failed to load fetch context",
            level=logging.ERROR,
            error_code="NEWS_FETCH_CONTEXT_LOAD_FAILED",
            fields={
                "search_artifact_id": search_id,
                "selection_artifact_id": selection_id,
                "exception": str(exc),
            },
        )
        return WorkflowNodeResult(
            update=build_fetch_node_error_update(
                f"Failed to retrieve search/selection artifacts: {str(exc)}"
            ),
            goto="END",
        )

    log_event(
        logger,
        event="news_fetch_started",
        message="news fetch started",
        fields={"selected_count": len(selected_indices)},
    )

    parsed_results = parse_news_search_result_items(
        list(raw_results),
        context="news fetch search results",
    )
    articles_to_fetch = build_articles_to_fetch(parsed_results, selected_indices)

    async def fetch_all() -> list[FetchContentResult]:
        tasks = [
            fetch_clean_text_async_fn(res.link)
            if res.link
            else asyncio.sleep(
                0,
                result=FetchContentResult.fail(
                    code="missing_url",
                    reason="missing article URL",
                ),
            )
            for res in articles_to_fetch
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        fetch_results: list[FetchContentResult] = []
        for index, result in enumerate(raw_results):
            if isinstance(result, Exception):
                url = (
                    articles_to_fetch[index].link
                    if index < len(articles_to_fetch)
                    else None
                )
                log_event(
                    logger,
                    event="news_fetch_async_item_failed",
                    message="news fetch failed for one article; continuing",
                    level=logging.WARNING,
                    error_code="NEWS_FETCH_ASYNC_ITEM_FAILED",
                    fields={
                        "index": index,
                        "url": url,
                        "exception": str(result),
                    },
                )
                article_errors.append(
                    f"Content fetch failed for article index {index}: {str(result)}"
                )
                _append_source_once(degrade_sources, "async_fetch_item")
                fetch_results.append(
                    FetchContentResult.fail(
                        code="fetch_exception",
                        reason=str(result),
                    )
                )
                continue
            fetch_results.append(result)
        return fetch_results

    fetch_results = await fetch_all()
    full_contents = [item.content for item in fetch_results]

    attempted_count = len(fetch_results)
    success_count = sum(1 for item in fetch_results if item.is_success)
    fail_count = attempted_count - success_count
    fail_reason_counts: dict[str, int] = {}
    status_code_counts: dict[str, int] = {}
    for item in fetch_results:
        if item.is_success:
            continue
        code = item.failure_code or "unknown_failure"
        fail_reason_counts[code] = fail_reason_counts.get(code, 0) + 1
        if item.http_status is not None:
            status_key = str(item.http_status)
            status_code_counts[status_key] = status_code_counts.get(status_key, 0) + 1

    if fail_count > 0:
        _append_source_once(degrade_sources, "content_fetch")
        summary = f"Content fetch degraded: {fail_count}/{attempted_count} failed"
        if fail_reason_counts:
            summary = f"{summary} (reasons={fail_reason_counts})"
        if status_code_counts:
            summary = f"{summary}, status_codes={status_code_counts}"
        article_errors.insert(0, summary)

    ticker = resolved_ticker_from_state(state) or ""
    timestamp = int(time.time())

    fetch_result = await build_news_items_from_fetch_results(
        articles_to_fetch=articles_to_fetch,
        full_contents=full_contents,
        ticker=ticker,
        timestamp=timestamp,
        port=port,
        generate_news_id_fn=generate_news_id_fn,
        get_source_reliability_fn=get_source_reliability_fn,
        item_factory=item_factory,
        source_factory=source_factory,
    )
    news_items = fetch_result.news_items
    if fetch_result.article_errors:
        _append_source_once(degrade_sources, "news_item_build")
        article_errors.extend(fetch_result.article_errors)

    news_items_id = None
    try:
        news_items_id = await port.save_news_items(
            data={"news_items": news_items},
            produced_by="financial_news_research.fetch_node",
            key_prefix=f"news_items_{ticker}_{timestamp}",
        )
    except Exception as exc:
        log_event(
            logger,
            event="news_fetch_artifact_save_failed",
            message="failed to save fetched news items artifact",
            level=logging.ERROR,
            error_code="NEWS_FETCH_ARTIFACT_SAVE_FAILED",
            fields={"ticker": ticker, "exception": str(exc)},
        )
        article_errors.append(f"Failed to save news items artifact: {str(exc)}")
        _append_source_once(degrade_sources, "artifact_save")

    is_degraded = bool(article_errors)
    log_event(
        logger,
        event="news_fetch_completed",
        message="news fetch completed",
        fields={
            "ticker": ticker,
            "selected_count": len(selected_indices),
            "fetched_count": len(articles_to_fetch),
            "fetch_attempted_count": attempted_count,
            "fetch_success_count": success_count,
            "fetch_fail_count": fail_count,
            "fetch_fail_reason_counts": fail_reason_counts,
            "fetch_status_code_counts": status_code_counts,
            "news_items_count": len(news_items),
            "article_errors_count": len(article_errors),
            "is_degraded": is_degraded,
            "degrade_sources": degrade_sources,
            "news_items_artifact_id": news_items_id,
        },
    )
    if is_degraded:
        log_event(
            logger,
            event="news_fetch_degraded",
            message="news fetch degraded with partial failures",
            level=logging.WARNING,
            error_code="NEWS_FETCH_DEGRADED",
            fields={
                "ticker": ticker,
                "search_artifact_id": search_id,
                "selection_artifact_id": selection_id,
                "selected_count": len(selected_indices),
                "news_items_count": len(news_items),
                "article_errors_count": len(article_errors),
                "fetch_attempted_count": attempted_count,
                "fetch_success_count": success_count,
                "fetch_fail_count": fail_count,
                "fetch_fail_reason_counts": fail_reason_counts,
                "fetch_status_code_counts": status_code_counts,
                "degrade_sources": degrade_sources,
                "degrade_reason": _truncate_error_message(article_errors[0]),
            },
        )

    return WorkflowNodeResult(
        update=build_fetch_node_update(
            news_items_id=news_items_id, article_errors=article_errors
        ),
        goto="analyst_node",
    )
