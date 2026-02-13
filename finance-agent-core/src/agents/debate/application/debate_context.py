from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from langchain_core.messages import BaseMessage

from src.agents.debate.application.state_readers import (
    artifact_ref_id_from_context,
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
    cached_reports: str | None


@dataclass(frozen=True)
class DebateConversationContext:
    ticker: str | None
    history: list[BaseMessage]
    debate_context: Mapping[str, object]


def build_debate_artifact_context(state: Mapping[str, object]) -> DebateArtifactContext:
    ticker = resolved_ticker_from_state(state)
    financial_reports_artifact_id = _fundamental_reports_artifact_id(state)
    news_artifact_id = _news_artifact_id(state)
    technical_artifact_id = _technical_artifact_id(state)
    cached_reports = _cached_reports(state)

    return DebateArtifactContext(
        ticker=ticker,
        financial_reports_artifact_id=financial_reports_artifact_id,
        news_artifact_id=news_artifact_id,
        technical_artifact_id=technical_artifact_id,
        cached_reports=cached_reports,
    )


def build_debate_conversation_context(
    state: Mapping[str, object],
) -> DebateConversationContext:
    return DebateConversationContext(
        ticker=resolved_ticker_from_state(state),
        history=history_from_state(state),
        debate_context=debate_context_from_state(state),
    )


def _fundamental_reports_artifact_id(state: Mapping[str, object]) -> str | None:
    fundamental_ctx = state.get("fundamental_analysis", {})
    if not isinstance(fundamental_ctx, Mapping):
        return None
    artifact_id = fundamental_ctx.get("financial_reports_artifact_id")
    if not isinstance(artifact_id, str):
        return None
    return artifact_id


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


def _cached_reports(state: Mapping[str, object]) -> str | None:
    cached_reports = state.get("compressed_reports")
    if not isinstance(cached_reports, str):
        return None
    if not cached_reports:
        return None
    return cached_reports
