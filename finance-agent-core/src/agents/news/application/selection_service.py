from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from src.agents.news.interface.contracts import SelectorResponseModel
from src.agents.news.interface.prompt_renderers import (
    format_selector_input as format_selector_input_interface,
)
from src.shared.kernel.types import JSONObject
from src.shared.llm.contracts import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    LLMProviderPort,
    ModelRoute,
    StructuredRequest,
)


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


async def run_selector_with_resilience(
    *,
    llm_provider: LLMProviderPort,
    llm_route: ModelRoute,
    ticker: str | None,
    formatted_results: str,
    raw_results: list[JSONObject],
    system_prompt: str,
    user_prompt: str,
) -> SelectorExecutionResult:
    try:
        request = CompletionRequest(
            messages=(
                ChatMessage(role=ChatRole.SYSTEM, content=system_prompt),
                ChatMessage(
                    role=ChatRole.USER,
                    content=user_prompt.format(
                        ticker=ticker or "UNKNOWN",
                        search_results=formatted_results,
                    ),
                ),
            ),
            route=llm_route,
            request_id=f"news-selector-{uuid4().hex}",
            operation="news.select_articles",
            timeout_seconds=60.0,
        )
        response = await llm_provider.acomplete_structured(
            StructuredRequest[SelectorResponseModel](
                completion=request,
                response_schema=SelectorResponseModel,
            )
        )
        url_to_index = {
            result.get("link"): index
            for index, result in enumerate(raw_results)
            if result.get("link")
        }
        indices = [
            url_to_index[article.url]
            for article in response.selected_articles
            if article.url in url_to_index
        ]
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
