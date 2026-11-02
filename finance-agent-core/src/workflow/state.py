"""Shared transport state for the root workflow composition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, TypeVar

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict

from src.artifacts.public import ArtifactReferencePayload
from src.shared.cross_agent.domain.market_identity import CompanyProfile

_Value = TypeVar("_Value")


def last_value(left: _Value | None, right: _Value | None) -> _Value | None:
    return right if right is not None else left


def replace_value(_left: _Value, right: _Value) -> _Value:
    """Replace root transport values on a new run, including empty values."""
    return right


def merge_resettable_dict(
    left: Mapping[str, _Value] | None,
    right: Mapping[str, _Value] | None,
) -> dict[str, _Value]:
    """Merge parallel transport updates; ``None`` explicitly resets a run."""
    if right is None:
        return {}
    return {**(left or {}), **right}


def merge_resettable_logs(
    left: list[dict[str, object]] | None,
    right: list[dict[str, object]] | None,
) -> list[dict[str, object]]:
    """Merge branch diagnostics idempotently; ``None`` explicitly resets a run."""
    if right is None:
        return []
    merged = list(left or [])
    for entry in right:
        if entry not in merged:
            merged.append(entry)
    return merged


class AgentState(TypedDict):
    """State shared between root-level agent subgraphs.

    Agent-specific contexts remain inside their owning subgraphs. The root
    carries only the request, resolved company identity, artifact references,
    conversation messages, and workflow telemetry.
    """

    user_query: Annotated[str | None, last_value]
    messages: Annotated[list[AnyMessage], add_messages]
    company_profile: Annotated[CompanyProfile | None, replace_value]
    artifact_references: Annotated[
        dict[str, ArtifactReferencePayload] | None, merge_resettable_dict
    ]
    workflow_activity_statuses: Annotated[dict[str, str] | None, merge_resettable_dict]
    active_activity_id: Annotated[str | None, replace_value]
    workflow_activity_updates: Annotated[dict[str, str] | None, merge_resettable_dict]
    error_logs: Annotated[list[dict[str, object]] | None, merge_resettable_logs]
