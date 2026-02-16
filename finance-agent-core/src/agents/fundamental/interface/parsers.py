from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from src.shared.kernel.types import JSONObject


class _ParamsModelLike(Protocol):
    def model_dump(self, *, mode: str) -> JSONObject: ...


class _ParamsSchemaLike(Protocol):
    def __call__(self, **kwargs: object) -> _ParamsModelLike: ...


class _ValuationCalculatorLike(Protocol):
    def __call__(self, params: object) -> object: ...


@dataclass(frozen=True)
class ValuationSkillRuntime:
    schema: _ParamsSchemaLike
    calculator: _ValuationCalculatorLike


def parse_valuation_skill_runtime(
    value: object, *, context: str
) -> ValuationSkillRuntime:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be a mapping")

    schema = value.get("schema")
    calculator = value.get("calculator")

    if not callable(schema):
        raise TypeError(f"{context}.schema must be callable")
    if not callable(calculator):
        raise TypeError(f"{context}.calculator must be callable")

    return ValuationSkillRuntime(
        schema=cast(_ParamsSchemaLike, schema),
        calculator=cast(_ValuationCalculatorLike, calculator),
    )


def parse_calculation_metrics(value: object, *, context: str) -> JSONObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must serialize to an object")
    return dict(value)
