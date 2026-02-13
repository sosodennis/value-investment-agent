from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import date, datetime
from enum import Enum
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from src.common.types import JSONObject, JSONValue

TModel = TypeVar("TModel", bound=BaseModel)


def as_mapping(value: object, context: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json")
        if not isinstance(dumped, dict):
            raise TypeError(f"{context} must dump to dict")
        return dumped
    raise TypeError(f"{context} must be a mapping, got {type(value)!r}")


def to_json(value: object, context: str) -> JSONValue:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return to_json(value.value, context)
    if isinstance(value, BaseModel):
        return to_json(value.model_dump(mode="json"), context)
    if isinstance(value, Mapping):
        payload: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{context} has non-string key")
            payload[key] = to_json(item, f"{context}.{key}")
        return payload
    if isinstance(value, list):
        return [
            to_json(item, f"{context}[{index}]") for index, item in enumerate(value)
        ]
    raise TypeError(f"{context} has unsupported JSON type: {type(value)!r}")


def to_string(value: object, context: str) -> str:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        value = value.value
    if not isinstance(value, str):
        raise TypeError(f"{context} must be a string")
    return value


def to_optional_string(value: object, context: str) -> str | None:
    if value is None:
        return None
    return to_string(value, context)


def to_number(value: object, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{context} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise TypeError(f"{context} must be finite")
    return number


def to_optional_number(value: object, context: str) -> float | None:
    if value is None:
        return None
    return to_number(value, context)


def symbol(
    value: object, context: str, allowed: Mapping[str, str], *, uppercase: bool = False
) -> str:
    token = to_string(value, context).strip()
    key = token.upper() if uppercase else token.lower()
    mapped = allowed.get(key)
    if mapped is None:
        raise TypeError(f"{context} has unsupported value: {token!r}")
    return mapped


def normalize_series_map(value: object, context: str) -> dict[str, float]:
    mapping = as_mapping(value, context)
    output: dict[str, float] = {}
    for key, item in mapping.items():
        if isinstance(item, bool):
            raise TypeError(f"{context}.{key} cannot be boolean")
        if item is None:
            continue
        if not isinstance(item, int | float):
            raise TypeError(f"{context}.{key} must be a number")
        num = float(item)
        if not math.isfinite(num):
            continue
        output[str(key)] = num
    return output


def validate_and_dump(
    model_type: type[TModel], value: object, context: str, *, exclude_none: bool = False
) -> JSONObject:
    try:
        model = model_type.model_validate(value)
    except ValidationError as exc:
        raise TypeError(f"{context} validation failed: {exc}") from exc
    dumped = model.model_dump(mode="json", exclude_none=exclude_none)
    if not isinstance(dumped, dict):
        raise TypeError(f"{context} must serialize to object")
    return dumped
