from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Protocol

from src.agents.news.interface.contracts import (
    FinancialNewsItemModel,
    NewsSearchResultItemModel,
)
from src.shared.kernel.types import JSONObject


class _ModelDumpLike(Protocol):
    def model_dump(self, *, mode: str) -> JSONObject: ...


def _extract_json_payload(content: str, *, context: str) -> object:
    stripped = content
    if "```json" in stripped:
        stripped = stripped.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in stripped:
        stripped = stripped.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise TypeError(f"{context} must contain valid JSON payload") from exc


def parse_selector_selected_urls(content: str, *, context: str) -> list[str]:
    payload = _extract_json_payload(content, context=context)
    if not isinstance(payload, Mapping):
        raise TypeError(f"{context} must decode to a JSON object")

    selected_articles = payload.get("selected_articles")
    if not isinstance(selected_articles, list):
        raise TypeError(f"{context} missing selected_articles array")

    urls: list[str] = []
    for article in selected_articles:
        if not isinstance(article, Mapping):
            continue
        url = article.get("url")
        if isinstance(url, str) and url:
            urls.append(url)
    return urls


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
