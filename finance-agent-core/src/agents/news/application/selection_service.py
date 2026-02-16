from __future__ import annotations

from dataclasses import dataclass

from src.agents.news.application.ports import ChainLike
from src.agents.news.interface.parsers import parse_selector_selected_urls
from src.agents.news.interface.prompt_renderers import (
    format_selector_input as format_selector_input_interface,
)
from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class SelectorExecutionResult:
    selected_indices: list[int]
    is_degraded: bool
    error_message: str


def build_selector_degraded_indices(raw_results: list[JSONObject]) -> list[int]:
    return list(range(min(3, len(raw_results))))


def normalize_selected_indices(
    selected_indices: list[int], *, limit: int = 10
) -> list[int]:
    return list(dict.fromkeys(selected_indices))[:limit]


def format_selector_input(cleaned_results: list[JSONObject]) -> str:
    return format_selector_input_interface(cleaned_results)


def run_selector_with_resilience(
    *,
    chain: ChainLike,
    ticker: str | None,
    formatted_results: str,
    raw_results: list[JSONObject],
) -> SelectorExecutionResult:
    try:
        response = chain.invoke({"ticker": ticker, "search_results": formatted_results})
        selected_urls = parse_selector_selected_urls(
            str(response.content),
            context="news selector response",
        )
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
            selected_indices=build_selector_degraded_indices(raw_results),
            is_degraded=True,
            error_message=str(exc),
        )
