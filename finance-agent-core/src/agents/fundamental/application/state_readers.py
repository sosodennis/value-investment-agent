from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.shared.cross_agent.domain.market_identity import CompanyProfile


@dataclass(frozen=True)
class IntentState:
    context: dict[str, object]
    resolved_ticker: str | None
    profile: CompanyProfile | None


@dataclass(frozen=True)
class FundamentalState:
    context: dict[str, object]
    model_type: str | None
    financial_reports_artifact_id: str | None


def read_intent_state(state: Mapping[str, object]) -> IntentState:
    intent_ctx_raw = state.get("intent_extraction", {})
    intent_ctx = intent_ctx_raw if isinstance(intent_ctx_raw, Mapping) else {}
    context = dict(intent_ctx)

    resolved_ticker_raw = context.get("resolved_ticker")
    resolved_ticker = (
        resolved_ticker_raw
        if isinstance(resolved_ticker_raw, str) and resolved_ticker_raw
        else None
    )

    profile_data = context.get("company_profile")
    profile = (
        CompanyProfile(**profile_data) if isinstance(profile_data, Mapping) else None
    )

    return IntentState(
        context=context,
        resolved_ticker=resolved_ticker,
        profile=profile,
    )


def read_fundamental_state(state: Mapping[str, object]) -> FundamentalState:
    fundamental_raw = state.get("fundamental_analysis", {})
    fundamental_ctx = fundamental_raw if isinstance(fundamental_raw, Mapping) else {}
    context = dict(fundamental_ctx)

    model_type_raw = context.get("model_type")
    model_type = (
        model_type_raw if isinstance(model_type_raw, str) and model_type_raw else None
    )

    reports_artifact_id_raw = context.get("financial_reports_artifact_id")
    reports_artifact_id = (
        reports_artifact_id_raw
        if isinstance(reports_artifact_id_raw, str) and reports_artifact_id_raw
        else None
    )

    return FundamentalState(
        context=context,
        model_type=model_type,
        financial_reports_artifact_id=reports_artifact_id,
    )
