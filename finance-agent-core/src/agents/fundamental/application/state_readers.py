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


def _read_non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_company_profile(profile_data: object) -> CompanyProfile | None:
    if not isinstance(profile_data, Mapping):
        return None
    try:
        profile = CompanyProfile(**dict(profile_data))
    except Exception:
        return None
    return profile


def read_intent_state(state: Mapping[str, object]) -> IntentState:
    intent_ctx_raw = state.get("intent_extraction", {})
    intent_ctx = intent_ctx_raw if isinstance(intent_ctx_raw, Mapping) else {}
    context = dict(intent_ctx)

    resolved_ticker = _read_non_empty_string(context.get("resolved_ticker"))
    profile = _read_company_profile(context.get("company_profile"))

    return IntentState(
        context=context,
        resolved_ticker=resolved_ticker,
        profile=profile,
    )


def read_fundamental_state(state: Mapping[str, object]) -> FundamentalState:
    fundamental_raw = state.get("fundamental_analysis", {})
    fundamental_ctx = fundamental_raw if isinstance(fundamental_raw, Mapping) else {}
    context = dict(fundamental_ctx)

    model_type = _read_non_empty_string(context.get("model_type"))
    reports_artifact_id = _read_non_empty_string(
        context.get("financial_reports_artifact_id")
    )

    return FundamentalState(
        context=context,
        model_type=model_type,
        financial_reports_artifact_id=reports_artifact_id,
    )
