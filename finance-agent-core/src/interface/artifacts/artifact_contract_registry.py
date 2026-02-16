from __future__ import annotations

from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

from src.interface.artifacts.artifact_contract_specs import (
    ARTIFACT_CONTRACT_SPEC_BY_KIND,
    ArtifactContractSpec,
)
from src.shared.kernel.types import JSONObject

_ModelT = TypeVar("_ModelT", bound=BaseModel)


def _get_spec(kind: str, *, context: str) -> ArtifactContractSpec:
    spec = ARTIFACT_CONTRACT_SPEC_BY_KIND.get(kind)
    if spec is None:
        raise TypeError(f"{context} has unsupported artifact kind: {kind!r}")
    return spec


def parse_artifact_data_model(
    kind: str,
    value: object,
    *,
    context: str,
) -> BaseModel:
    spec = _get_spec(kind, context=context)
    try:
        return spec.model.model_validate(value)
    except ValidationError as exc:
        raise TypeError(f"{context} validation failed: {exc}") from exc


def parse_artifact_data_model_as(
    kind: str,
    value: object,
    *,
    model: type[_ModelT],
    context: str,
) -> _ModelT:
    parsed = parse_artifact_data_model(kind, value, context=context)
    if not isinstance(parsed, model):
        raise TypeError(
            f"{context} parsed model type mismatch: got {type(parsed)!r}, expected {model!r}"
        )
    return parsed


def parse_artifact_data_json(
    kind: str,
    value: object,
    *,
    context: str,
) -> JSONObject:
    spec = _get_spec(kind, context=context)
    try:
        parsed = spec.model.model_validate(value)
    except ValidationError as exc:
        raise TypeError(f"{context} validation failed: {exc}") from exc

    dumped = parsed.model_dump(mode="json", exclude_none=spec.dump_exclude_none)
    if not isinstance(dumped, dict):
        raise TypeError(f"{context} must serialize to object")
    return cast(JSONObject, dumped)


def canonicalize_artifact_data_by_kind(
    kind: str,
    value: object,
    *,
    context: str,
) -> JSONObject:
    return parse_artifact_data_json(kind, value, context=context)
