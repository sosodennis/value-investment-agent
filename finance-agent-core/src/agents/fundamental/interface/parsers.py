from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from src.agents.fundamental.interface.contracts import parse_financial_reports_model
from src.shared.kernel.types import JSONObject


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
class FinancialHealthPayload:
    financial_reports: list[JSONObject]
    forward_signals: list[JSONObject] | None


def _parse_forward_signals(value: object) -> list[JSONObject] | None:
    if not isinstance(value, list):
        return None
    normalized: list[JSONObject] = []
    for item in value:
        if isinstance(item, Mapping):
            normalized.append(dict(item))
    return normalized or None


def parse_financial_health_payload(
    value: object,
    *,
    context: str,
) -> FinancialHealthPayload:
    reports_raw: object
    forward_signals_raw: object = None
    if isinstance(value, Mapping):
        reports_raw = value.get("financial_reports")
        if reports_raw is None:
            reports_raw = value.get("reports")
        if reports_raw is None:
            reports_raw = []
        forward_signals_raw = value.get("forward_signals")
    else:
        reports_raw = value

    return FinancialHealthPayload(
        financial_reports=parse_financial_reports_model(
            reports_raw,
            context=f"{context}.financial_reports",
        ),
        forward_signals=_parse_forward_signals(forward_signals_raw),
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
