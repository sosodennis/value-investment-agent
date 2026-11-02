from __future__ import annotations

from collections.abc import Mapping

from langchain_core.messages import AIMessage, BaseMessage

from src.shared.cross_agent.domain.market_identity import CompanyProfile


def resolved_ticker_from_state(state: Mapping[str, object]) -> str | None:
    profile = state.get("company_profile")
    if isinstance(profile, CompanyProfile):
        ticker = profile.ticker.strip()
        return ticker or None
    if isinstance(profile, Mapping):
        ticker = profile.get("ticker")
        if isinstance(ticker, str) and ticker.strip():
            return ticker.strip()
    return None


def history_from_state(state: Mapping[str, object]) -> list[BaseMessage]:
    history_raw = state.get("history", [])
    if not isinstance(history_raw, list):
        return []
    return [msg for msg in history_raw if isinstance(msg, BaseMessage)]


def debate_context_from_state(state: Mapping[str, object]) -> Mapping[str, object]:
    debate = state.get("debate", {})
    if not isinstance(debate, Mapping):
        return {}
    return debate


def bull_thesis_from_state(state: Mapping[str, object]) -> str | None:
    return _thesis_from_state(state, key="bull_thesis")


def bear_thesis_from_state(state: Mapping[str, object]) -> str | None:
    return _thesis_from_state(state, key="bear_thesis")


def get_last_message_from_role(history: list[BaseMessage], role_name: str) -> str:
    """Extract the last message from a specific role with resilience handling."""
    if not history:
        return ""
    for msg in reversed(history):
        if getattr(msg, "name", None) == role_name:
            return str(msg.content)
        if (
            isinstance(msg, AIMessage)
            and msg.additional_kwargs.get("name") == role_name
        ):
            return str(msg.content)
    return ""


def _thesis_from_state(state: Mapping[str, object], *, key: str) -> str | None:
    value = state.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
