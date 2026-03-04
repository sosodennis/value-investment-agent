from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from langchain_core.messages import BaseMessage

from src.agents.debate.application.state_readers import (
    artifact_ref_id_from_context,
    bear_thesis_from_state,
    bull_thesis_from_state,
    debate_context_from_state,
    history_from_state,
    resolved_ticker_from_state,
)
from src.shared.kernel.types import JSONObject


@dataclass(frozen=True)
class DebateArtifactContext:
    ticker: str | None
    financial_reports_artifact_id: str | None
    news_artifact_id: str | None
    technical_artifact_id: str | None
    fundamental_valuation_preview: JSONObject | None
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
    financial_reports_artifact_id = _fundamental_reports_artifact_id(state)
    news_artifact_id = _news_artifact_id(state)
    technical_artifact_id = _technical_artifact_id(state)
    fundamental_valuation_preview = _fundamental_valuation_preview(state)
    cached_context_summary_text = _cached_context_summary_text(state)
    cached_facts_registry_text = _cached_facts_registry_text(state)

    return DebateArtifactContext(
        ticker=ticker,
        financial_reports_artifact_id=financial_reports_artifact_id,
        news_artifact_id=news_artifact_id,
        technical_artifact_id=technical_artifact_id,
        fundamental_valuation_preview=fundamental_valuation_preview,
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


def _fundamental_reports_artifact_id(state: Mapping[str, object]) -> str | None:
    fundamental_ctx = state.get("fundamental_analysis", {})
    if not isinstance(fundamental_ctx, Mapping):
        return None
    artifact_id = fundamental_ctx.get("financial_reports_artifact_id")
    if not isinstance(artifact_id, str):
        return None
    return artifact_id


def _fundamental_valuation_preview(state: Mapping[str, object]) -> JSONObject | None:
    fundamental_ctx = state.get("fundamental_analysis", {})
    if not isinstance(fundamental_ctx, Mapping):
        return None
    artifact_raw = fundamental_ctx.get("artifact")
    if not isinstance(artifact_raw, Mapping):
        return None
    preview_raw = artifact_raw.get("preview")
    if not isinstance(preview_raw, Mapping):
        return None
    return dict(preview_raw)


def _news_artifact_id(state: Mapping[str, object]) -> str | None:
    news_ctx = state.get("financial_news_research", {})
    if not isinstance(news_ctx, Mapping):
        return None
    return artifact_ref_id_from_context(news_ctx)


def _technical_artifact_id(state: Mapping[str, object]) -> str | None:
    technical_ctx = state.get("technical_analysis", {})
    if not isinstance(technical_ctx, Mapping):
        return None
    return artifact_ref_id_from_context(technical_ctx)


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
