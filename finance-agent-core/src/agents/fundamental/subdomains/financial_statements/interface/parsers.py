from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from src.agents.fundamental.subdomains.financial_statements.interface.contracts import (
    parse_financial_reports_model,
)
from src.shared.kernel.types import JSONObject, JSONValue


class _ParamsModelLike(Protocol):
    def model_dump(self, *, mode: str) -> JSONObject: ...


class _ParamsSchemaLike(Protocol):
    def __call__(self, **kwargs: object) -> _ParamsModelLike: ...


class _ValuationCalculatorLike(Protocol):
    def __call__(self, params: object) -> object: ...


class _ValuationAuditResultLike(Protocol):
    passed: bool
    messages: list[str]


class _ValuationAuditorLike(Protocol):
    def __call__(self, params: object) -> _ValuationAuditResultLike: ...


@dataclass(frozen=True)
class ValuationModelRuntime:
    schema: _ParamsSchemaLike
    calculator: _ValuationCalculatorLike
    auditor: _ValuationAuditorLike


@dataclass(frozen=True)
class FinancialStatementsPayload:
    financial_reports: list[JSONObject]
    diagnostics: JSONObject | None
    quality_gates: JSONObject | None


def _parse_optional_object(
    value: object,
    *,
    context: str,
) -> JSONObject | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be an object or null")

    normalized: JSONObject = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(f"{context} keys must be strings")
        normalized[key] = cast(JSONValue, item)
    return normalized


def parse_financial_statements_payload(
    value: object,
    *,
    context: str,
) -> FinancialStatementsPayload:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be a mapping")

    required_keys = (
        "financial_reports",
        "diagnostics",
        "quality_gates",
    )
    for key in required_keys:
        if key not in value:
            raise TypeError(f"{context}.{key} is required")

    reports_raw = value.get("financial_reports")
    diagnostics_raw = value.get("diagnostics")
    quality_gates_raw = value.get("quality_gates")

    return FinancialStatementsPayload(
        financial_reports=parse_financial_reports_model(
            reports_raw,
            context=f"{context}.financial_reports",
        ),
        diagnostics=_parse_optional_object(
            diagnostics_raw,
            context=f"{context}.diagnostics",
        ),
        quality_gates=_parse_optional_object(
            quality_gates_raw,
            context=f"{context}.quality_gates",
        ),
    )


def parse_valuation_model_runtime(
    value: object, *, context: str
) -> ValuationModelRuntime:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must be a mapping")

    schema = value.get("schema")
    calculator = value.get("calculator")
    auditor = value.get("auditor")

    if not callable(schema):
        raise TypeError(f"{context}.schema must be callable")
    if not callable(calculator):
        raise TypeError(f"{context}.calculator must be callable")
    if not callable(auditor):
        raise TypeError(f"{context}.auditor must be callable")

    return ValuationModelRuntime(
        schema=cast(_ParamsSchemaLike, schema),
        calculator=cast(_ValuationCalculatorLike, calculator),
        auditor=cast(_ValuationAuditorLike, auditor),
    )


def parse_calculation_metrics(value: object, *, context: str) -> JSONObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{context} must serialize to an object")
    return dict(value)
