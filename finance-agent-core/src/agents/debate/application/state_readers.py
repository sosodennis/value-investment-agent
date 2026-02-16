from __future__ import annotations

from collections.abc import Mapping

from langchain_core.messages import AIMessage, BaseMessage


def resolved_ticker_from_state(state: Mapping[str, object]) -> str | None:
    intent = state.get("intent_extraction", {})
    if not isinstance(intent, Mapping):
        return None
    ticker = intent.get("resolved_ticker")
    if not isinstance(ticker, str):
        return None
    ticker = ticker.strip()
    return ticker or None


def artifact_ref_id_from_context(ctx: Mapping[str, object]) -> str | None:
    artifact = ctx.get("artifact")
    if not isinstance(artifact, Mapping):
        return None
    reference = artifact.get("reference")
    if not isinstance(reference, Mapping):
        return None
    artifact_id = reference.get("artifact_id")
    if not isinstance(artifact_id, str):
        return None
    return artifact_id


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
