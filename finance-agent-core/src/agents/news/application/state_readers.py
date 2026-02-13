from __future__ import annotations

from collections.abc import Mapping


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


def intent_context_from_state(state: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping_or_empty(state.get("intent_extraction", {}))


def news_context_from_state(state: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping_or_empty(state.get("financial_news_research", {}))


def resolved_ticker_from_state(state: Mapping[str, object]) -> str | None:
    ticker = intent_context_from_state(state).get("resolved_ticker")
    if isinstance(ticker, str) and ticker:
        return ticker
    return None


def company_name_from_state(state: Mapping[str, object]) -> str | None:
    profile = intent_context_from_state(state).get("company_profile")
    if isinstance(profile, Mapping):
        name = profile.get("name")
        if isinstance(name, str) and name:
            return name
    return None


def search_artifact_id_from_state(state: Mapping[str, object]) -> object:
    return news_context_from_state(state).get("search_artifact_id")


def selection_artifact_id_from_state(state: Mapping[str, object]) -> object:
    return news_context_from_state(state).get("selection_artifact_id")


def news_items_artifact_id_from_state(state: Mapping[str, object]) -> object:
    return news_context_from_state(state).get("news_items_artifact_id")


def aggregator_ticker_from_state(state: Mapping[str, object]) -> str:
    ticker_raw = state.get("ticker")
    if isinstance(ticker_raw, str) and ticker_raw:
        return ticker_raw
    return "UNKNOWN"
