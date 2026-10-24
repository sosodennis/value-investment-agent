from __future__ import annotations

import logging

from pydantic import ValidationError

from src.agents.intent.application.ports import IntentWebSearchResult
from src.search import SearchClientError, WebSearchRequest, get_search_client
from src.shared.kernel.tools.logger import bounded_text, get_logger, log_event

logger = get_logger(__name__)


def web_search(query: str) -> IntentWebSearchResult:
    expanded_query = query
    if "ticker" in query.lower() or "stock" in query.lower():
        if "share class" not in query.lower():
            expanded_query += " share classes tickers"
    try:
        result = get_search_client().search_web(WebSearchRequest(query=expanded_query))
        if not result.results:
            return IntentWebSearchResult(
                content="",
                failure_code="INTENT_WEB_SEARCH_EMPTY",
                failure_reason="no results found",
                fallback_mode="yahoo_only",
            )
        content = "\\n---\\n".join(
            f"[{index}] Source: {item.title}\\nContent: {item.snippet}\\n"
            for index, item in enumerate(result.results, 1)
        )
        return IntentWebSearchResult(content=content)
    except (SearchClientError, ValidationError) as exc:
        service_code = (
            exc.code if isinstance(exc, SearchClientError) else "INVALID_REQUEST"
        )
        code = (
            "INTENT_WEB_SEARCH_EMPTY"
            if service_code == "NO_RESULTS"
            else "INTENT_WEB_SEARCH_FAILED"
        )
        log_event(
            logger,
            event="intent_web_search_failed",
            message="intent web search failed",
            level=logging.WARNING,
            error_code=code,
            fields={"error_code": service_code, "reason": bounded_text(exc)},
        )
        return IntentWebSearchResult(
            content="",
            failure_code=code,
            failure_reason=bounded_text(exc),
            fallback_mode="yahoo_only",
        )
