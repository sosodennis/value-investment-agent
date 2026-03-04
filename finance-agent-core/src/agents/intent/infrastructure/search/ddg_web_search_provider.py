from __future__ import annotations

import logging
import os

from langchain_community.utilities import DuckDuckGoSearchAPIWrapper

from src.agents.intent.application.ports import IntentWebSearchResult
from src.shared.kernel.tools.logger import bounded_text, get_logger, log_event

logger = get_logger(__name__)

DEFAULT_DDGS_REGION = os.getenv("DDGS_REGION", "us-en")
DEFAULT_DDGS_BACKEND = os.getenv("DDGS_BACKEND", "duckduckgo")


def web_search(query: str) -> IntentWebSearchResult:
    try:
        if "ticker" in query.lower() or "stock" in query.lower():
            if "share class" not in query.lower():
                query += " share classes tickers"

        log_event(
            logger,
            event="intent_web_search_started",
            message="intent web search started",
            fields={"query": query},
        )

        search = DuckDuckGoSearchAPIWrapper(
            max_results=7,
            time="y",
            region=DEFAULT_DDGS_REGION,
            backend=DEFAULT_DDGS_BACKEND,
        )
        results = search.results(query, max_results=7)
        if not results:
            log_event(
                logger,
                event="intent_web_search_empty",
                message="intent web search returned no results",
                level=logging.WARNING,
                error_code="INTENT_WEB_SEARCH_EMPTY",
                fields={"query": query},
            )
            return IntentWebSearchResult(
                content="",
                failure_code="INTENT_WEB_SEARCH_EMPTY",
                failure_reason="no results found",
                fallback_mode="yahoo_only",
            )

        formatted_output: list[str] = []
        for i, res in enumerate(results, 1):
            title = res.get("title", "No Title")
            snippet = res.get("snippet", "No Snippet")
            formatted_output.append(f"[{i}] Source: {title}\\nContent: {snippet}\\n")

        return IntentWebSearchResult(content="\\n---\\n".join(formatted_output))
    except Exception as exc:
        bounded_exception = bounded_text(exc)
        exception_text = bounded_exception.lower()
        if "no results found" in exception_text:
            log_event(
                logger,
                event="intent_web_search_empty",
                message="intent web search returned no results",
                level=logging.WARNING,
                error_code="INTENT_WEB_SEARCH_EMPTY",
                fields={"query": query, "exception": bounded_exception},
            )
            return IntentWebSearchResult(
                content="",
                failure_code="INTENT_WEB_SEARCH_EMPTY",
                failure_reason=bounded_exception,
                fallback_mode="yahoo_only",
            )
        log_event(
            logger,
            event="intent_web_search_failed",
            message="intent web search failed",
            level=logging.ERROR,
            error_code="INTENT_WEB_SEARCH_FAILED",
            fields={"query": query, "exception": bounded_exception},
        )
        return IntentWebSearchResult(
            content="",
            failure_code="INTENT_WEB_SEARCH_FAILED",
            failure_reason=bounded_exception,
            fallback_mode="yahoo_only",
        )
