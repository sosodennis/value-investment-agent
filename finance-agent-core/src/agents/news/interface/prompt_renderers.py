from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from src.shared.kernel.types import JSONObject


def format_selector_input(cleaned_results: list[JSONObject]) -> str:
    formatted_list: list[str] = []
    for result in cleaned_results:
        categories = result.get("categories", [])
        categories_str = ", ".join([str(value).upper() for value in categories])
        formatted_list.append(
            f"""
Source: {result.get('source')} | [TAGS: {categories_str}] | Date: {result.get('date')}
Title: {result.get('title')}
Snippet: {result.get('snippet')}
URL: {result.get('link')}
--------------------------------------------------
"""
        )
    return "".join(formatted_list)


def build_analysis_chain_payload(
    *,
    ticker: str,
    item: JSONObject,
    content_to_analyze: str,
    finbert_summary: JSONObject | None,
) -> JSONObject:
    source_raw = item.get("source")
    source_info = source_raw if isinstance(source_raw, dict) else {}
    base_payload: JSONObject = {
        "ticker": ticker,
        "title": str(item.get("title", "Unknown")),
        "source": str(source_info.get("name", "Unknown")),
        "published_at": "N/A",
        "content": content_to_analyze,
    }

    categories_raw = item.get("categories", ["general"])
    categories = categories_raw if isinstance(categories_raw, list) else ["general"]
    base_payload["search_tag"] = ", ".join([str(value).upper() for value in categories])

    if finbert_summary is not None:
        base_payload["finbert_sentiment"] = str(
            finbert_summary.get("label", "NEUTRAL")
        ).upper()
        base_payload["finbert_confidence"] = str(
            finbert_summary.get("confidence", "0.0%")
        )
        base_payload["finbert_has_numbers"] = (
            "Yes" if bool(finbert_summary.get("has_numbers")) else "No"
        )
    return base_payload


def build_selector_chat_prompt(
    *, system_prompt: str, user_prompt: str
) -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("user", user_prompt)]
    )


def build_analyst_chat_prompts(
    *,
    system_prompt: str,
    user_prompt_basic: str,
    user_prompt_with_finbert: str,
) -> tuple[ChatPromptTemplate, ChatPromptTemplate]:
    prompt_basic = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("user", user_prompt_basic)]
    )
    prompt_finbert = ChatPromptTemplate.from_messages(
        [("system", system_prompt), ("user", user_prompt_with_finbert)]
    )
    return prompt_basic, prompt_finbert
