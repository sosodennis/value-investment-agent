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


def _read_non_empty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _read_company_profile(profile_data: object) -> CompanyProfile | None:
    if isinstance(profile_data, CompanyProfile):
        return profile_data
    if not isinstance(profile_data, Mapping):
        return None
    try:
        profile = CompanyProfile(**dict(profile_data))
    except Exception:
        return None
    return profile


def read_intent_state(state: Mapping[str, object]) -> IntentState:
    profile = _read_company_profile(state.get("company_profile"))
    context: dict[str, object] = {}
    if profile is not None:
        context["company_profile"] = profile.model_dump(mode="json")
        context["resolved_ticker"] = profile.ticker

    resolved_ticker = profile.ticker if profile is not None else None

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
    return FundamentalState(
        context=context,
        model_type=model_type,
    )
