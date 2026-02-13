from __future__ import annotations

from typing import Literal, TypeAlias

from typing_extensions import TypedDict

from src.common.contracts import AgentOutputKind

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]
JSONArray: TypeAlias = list[JSONValue]


class ArtifactReferencePayload(TypedDict):
    artifact_id: str
    download_url: str
    type: str


class AgentOutputArtifactPayload(TypedDict):
    kind: AgentOutputKind
    version: Literal["v1"]
    summary: str
    preview: JSONObject | None
    reference: ArtifactReferencePayload | None


class InterruptResumePayload(TypedDict, total=False):
    selected_symbol: str
    ticker: str
