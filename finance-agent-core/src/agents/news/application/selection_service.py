from __future__ import annotations

import json
from dataclasses import dataclass

from src.agents.news.application.ports import ChainLike
from src.agents.news.domain.services import (
    build_selector_fallback_indices as domain_build_selector_fallback_indices,
)
from src.agents.news.domain.services import (
    normalize_selected_indices as domain_normalize_selected_indices,
)
from src.agents.news.interface.prompt_formatters import (
    format_selector_input as format_selector_input_interface,
)
from src.common.types import JSONObject


@dataclass(frozen=True)
class SelectorExecutionResult:
    selected_indices: list[int]
    is_degraded: bool
    error_message: str


def build_selector_fallback_indices(raw_results: list[JSONObject]) -> list[int]:
    return domain_build_selector_fallback_indices(raw_results)


def normalize_selected_indices(
    selected_indices: list[int], *, limit: int = 10
) -> list[int]:
    return domain_normalize_selected_indices(selected_indices, limit=limit)


def format_selector_input(cleaned_results: list[JSONObject]) -> str:
    return format_selector_input_interface(cleaned_results)


def run_selector_with_fallback(
    *,
    chain: ChainLike,
    ticker: str | None,
    formatted_results: str,
    raw_results: list[JSONObject],
) -> SelectorExecutionResult:
    try:
        response = chain.invoke({"ticker": ticker, "search_results": formatted_results})
        content = str(response.content)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        selection_data = json.loads(content)
        selected_articles = selection_data.get("selected_articles")
        if selected_articles is None:
            return SelectorExecutionResult(
                selected_indices=build_selector_fallback_indices(raw_results),
                is_degraded=True,
                error_message="Selector returned no 'selected_articles' key.",
            )

        selected_urls = [
            article.get("url")
            for article in selected_articles
            if isinstance(article, dict) and article.get("url")
        ]
        url_to_index = {
            result.get("link"): index
            for index, result in enumerate(raw_results)
            if result.get("link")
        }
        indices = [url_to_index[url] for url in selected_urls if url in url_to_index]
        return SelectorExecutionResult(
            selected_indices=normalize_selected_indices(indices),
            is_degraded=False,
            error_message="",
        )
    except Exception as exc:
        return SelectorExecutionResult(
            selected_indices=build_selector_fallback_indices(raw_results),
            is_degraded=True,
            error_message=str(exc),
        )
