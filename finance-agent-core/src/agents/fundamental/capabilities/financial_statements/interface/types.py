from __future__ import annotations

import math
from typing import Annotated, TypeAlias

from pydantic import BeforeValidator

from src.interface.artifacts.artifact_model_shared import (
    to_json,
    to_number,
    to_optional_string,
    to_string,
)


def _parse_fundamental_text(value: object) -> str:
    return to_string(value, "fundamental artifact text")


FundamentalText: TypeAlias = Annotated[str, BeforeValidator(_parse_fundamental_text)]


def _parse_optional_fundamental_text(value: object) -> str | None:
    return to_optional_string(value, "fundamental optional text")


def _parse_optional_fundamental_number(value: object) -> float | None:
    if value is None:
        return None
    return to_number(value, "fundamental optional number")


OptionalFundamentalText: TypeAlias = Annotated[
    str | None,
    BeforeValidator(_parse_optional_fundamental_text),
]
OptionalFundamentalNumber: TypeAlias = Annotated[
    float | None,
    BeforeValidator(_parse_optional_fundamental_number),
]


def _parse_traceable_value(value: object) -> str | int | float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("traceable value cannot be boolean")
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    raise TypeError("traceable value must be string | number | null")


def _parse_traceable_provenance(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    parsed = to_json(value, "traceable.provenance")
    if not isinstance(parsed, dict):
        raise TypeError("traceable.provenance must serialize to object")
    return parsed


def _parse_traceable_optional_text(value: object) -> str | None:
    return to_optional_string(value, "traceable.optional_text")


TraceableValue: TypeAlias = Annotated[
    str | int | float | None,
    BeforeValidator(_parse_traceable_value),
]
TraceableProvenance: TypeAlias = Annotated[
    dict[str, object] | None,
    BeforeValidator(_parse_traceable_provenance),
]
TraceableOptionalText: TypeAlias = Annotated[
    str | None,
    BeforeValidator(_parse_traceable_optional_text),
]
