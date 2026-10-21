from __future__ import annotations

from typing import Protocol

from src.agents.news.interface.contracts import (
    FinancialNewsItemModel,
    NewsSearchResultItemModel,
)
from src.shared.kernel.types import JSONObject


class _ModelDumpLike(Protocol):
    def model_dump(self, *, mode: str) -> JSONObject: ...


def parse_structured_llm_output(value: _ModelDumpLike, *, context: str) -> JSONObject:
    dumped = value.model_dump(mode="json")
    if not isinstance(dumped, dict):
        raise TypeError(f"{context} output must serialize to JSON object")
    return dumped


def parse_news_search_result_items(
    values: list[object], *, context: str
) -> list[NewsSearchResultItemModel]:
    parsed_items: list[NewsSearchResultItemModel] = []
    for index, value in enumerate(values):
        try:
            parsed_items.append(NewsSearchResultItemModel.model_validate(value))
        except Exception as exc:
            raise TypeError(f"{context}[{index}] failed validation") from exc
    return parsed_items


def parse_news_items(
    values: list[object], *, context: str
) -> list[FinancialNewsItemModel]:
    parsed_items: list[FinancialNewsItemModel] = []
    for index, value in enumerate(values):
        try:
            parsed_items.append(FinancialNewsItemModel.model_validate(value))
        except Exception as exc:
            raise TypeError(f"{context}[{index}] failed validation") from exc
    return parsed_items
