from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, create_model

from src.interface.artifacts.artifact_contract_specs import (
    ARTIFACT_CONTRACT_SPECS,
    ArtifactContractSpec,
)


class ArtifactEnvelopeBase(BaseModel):
    version: Literal["v1"]
    produced_by: str
    created_at: str


def _envelope_model_name(kind: str) -> str:
    token = kind.strip()
    if not token:
        raise ValueError("artifact kind cannot be empty")
    return "".join(part.capitalize() for part in token.split("_")) + "Envelope"


def _build_envelope_model(spec: ArtifactContractSpec) -> type[BaseModel]:
    return create_model(
        _envelope_model_name(spec.kind),
        __base__=ArtifactEnvelopeBase,
        kind=(Literal[spec.kind], ...),
        data=(spec.model, ...),
    )


_ARTIFACT_ENVELOPE_MODELS: tuple[type[BaseModel], ...] = tuple(
    _build_envelope_model(spec) for spec in ARTIFACT_CONTRACT_SPECS
)


def _build_union(models: tuple[type[BaseModel], ...]) -> object:
    if not models:
        raise RuntimeError("artifact API envelope model registry cannot be empty")
    union: object = models[0]
    for model in models[1:]:
        union = union | model
    return union


ArtifactApiResponse = Annotated[
    _build_union(_ARTIFACT_ENVELOPE_MODELS),
    Field(discriminator="kind"),
]

_ARTIFACT_API_RESPONSE_ADAPTER = TypeAdapter(ArtifactApiResponse)


def validate_artifact_api_response(
    value: object, *, context: str = "artifact response"
) -> BaseModel:
    try:
        return _ARTIFACT_API_RESPONSE_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise TypeError(f"{context} validation failed: {exc}") from exc
