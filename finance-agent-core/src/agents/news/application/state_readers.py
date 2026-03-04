from __future__ import annotations

from collections.abc import Mapping


def intent_context_from_state(state: Mapping[str, object]) -> Mapping[str, object]:
    context = state.get("intent_extraction")
    if isinstance(context, Mapping):
        return context
    return {}


def news_context_from_state(state: Mapping[str, object]) -> Mapping[str, object]:
    context = state.get("financial_news_research")
    if isinstance(context, Mapping):
        return context
    return {}


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


def search_artifact_id_from_state(state: Mapping[str, object]) -> str | None:
    artifact_id = news_context_from_state(state).get("search_artifact_id")
    if isinstance(artifact_id, str) and artifact_id:
        return artifact_id
    return None


def selection_artifact_id_from_state(state: Mapping[str, object]) -> str | None:
    artifact_id = news_context_from_state(state).get("selection_artifact_id")
    if isinstance(artifact_id, str) and artifact_id:
        return artifact_id
    return None


def news_items_artifact_id_from_state(state: Mapping[str, object]) -> str | None:
    artifact_id = news_context_from_state(state).get("news_items_artifact_id")
    if isinstance(artifact_id, str) and artifact_id:
        return artifact_id
    return None


def aggregator_ticker_from_state(state: Mapping[str, object]) -> str:
    resolved = resolved_ticker_from_state(state)
    if resolved:
        return resolved
    return "UNKNOWN"
