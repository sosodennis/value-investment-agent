from __future__ import annotations

from typing import TypeAlias

from typing_extensions import TypedDict

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]
JSONArray: TypeAlias = list[JSONValue]


class ArtifactReferencePayload(TypedDict):
    artifact_id: str
    download_url: str
    type: str


class AgentOutputArtifactPayload(TypedDict):
    summary: str
    preview: JSONObject | None
    reference: ArtifactReferencePayload | None


class InterruptResumePayload(TypedDict, total=False):
    selected_symbol: str
    ticker: str
