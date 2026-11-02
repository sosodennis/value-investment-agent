from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from langchain_core.messages import BaseMessage

from src.agents.debate.application.state_readers import (
    bear_thesis_from_state,
    bull_thesis_from_state,
    debate_context_from_state,
    history_from_state,
    resolved_ticker_from_state,
)


@dataclass(frozen=True)
class DebateArtifactContext:
    ticker: str | None
    financial_reports_artifact_id: str | None
    news_artifact_id: str | None
    technical_artifact_id: str | None
    cached_context_summary_text: str | None
    cached_facts_registry_text: str | None


@dataclass(frozen=True)
class DebateConversationContext:
    ticker: str | None
    history: list[BaseMessage]
    debate_context: Mapping[str, object]
    bull_thesis: str | None
    bear_thesis: str | None


def build_debate_artifact_context(state: Mapping[str, object]) -> DebateArtifactContext:
    ticker = resolved_ticker_from_state(state)
    financial_reports_artifact_id = _artifact_reference_id(
        state, key="financial_reports"
    )
    news_artifact_id = _artifact_reference_id(state, key="news_analysis")
    technical_artifact_id = _artifact_reference_id(state, key="technical_analysis")
    cached_context_summary_text = _cached_context_summary_text(state)
    cached_facts_registry_text = _cached_facts_registry_text(state)

    return DebateArtifactContext(
        ticker=ticker,
        financial_reports_artifact_id=financial_reports_artifact_id,
        news_artifact_id=news_artifact_id,
        technical_artifact_id=technical_artifact_id,
        cached_context_summary_text=cached_context_summary_text,
        cached_facts_registry_text=cached_facts_registry_text,
    )


def build_debate_conversation_context(
    state: Mapping[str, object],
) -> DebateConversationContext:
    return DebateConversationContext(
        ticker=resolved_ticker_from_state(state),
        history=history_from_state(state),
        debate_context=debate_context_from_state(state),
        bull_thesis=bull_thesis_from_state(state),
        bear_thesis=bear_thesis_from_state(state),
    )


def _artifact_reference_id(state: Mapping[str, object], *, key: str) -> str | None:
    references = state.get("artifact_references", {})
    if not isinstance(references, Mapping):
        return None
    reference = references.get(key)
    if not isinstance(reference, Mapping):
        return None
    artifact_id = reference.get("artifact_id")
    if not isinstance(artifact_id, str) or not artifact_id:
        return None
    return artifact_id


def _cached_context_summary_text(state: Mapping[str, object]) -> str | None:
    cached_context_summary_text = state.get("context_summary_text")
    if not isinstance(cached_context_summary_text, str):
        return None
    if not cached_context_summary_text:
        return None
    return cached_context_summary_text


def _cached_facts_registry_text(state: Mapping[str, object]) -> str | None:
    cached_facts_registry_text = state.get("facts_registry_text")
    if not isinstance(cached_facts_registry_text, str):
        return None
    if not cached_facts_registry_text:
        return None
    return cached_facts_registry_text
