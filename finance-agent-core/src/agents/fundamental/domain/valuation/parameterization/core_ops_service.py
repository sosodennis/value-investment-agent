from __future__ import annotations

from collections.abc import Callable

from src.shared.kernel.traceable import (
    ManualProvenance,
    TraceableField,
)

from ..report_contract import FinancialReport
from .series_service import computed_field


def report_year(report: FinancialReport) -> int:
    value = report.base.fiscal_year.value
    if value is None:
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return -1


def sort_reports_by_year_desc(
    reports: list[FinancialReport],
) -> list[FinancialReport]:
    return sorted(reports, key=report_year, reverse=True)


def missing_field(name: str, reason: str) -> TraceableField[float]:
    return TraceableField(
        name=name,
        value=None,
        provenance=ManualProvenance(description=reason),
    )


def ratio(
    name: str,
    numerator: TraceableField[float],
    denominator: TraceableField[float],
    expression: str,
) -> TraceableField[float]:
    if numerator.value is None or denominator.value in (None, 0):
        return missing_field(name, f"Missing or zero denominator for {expression}")
    value = float(numerator.value) / float(denominator.value)
    return computed_field(
        name=name,
        value=value,
        op_code="DIV",
        expression=expression,
        inputs={numerator.name: numerator, denominator.name: denominator},
    )


def ratio_with_optional_inputs(
    *,
    name: str,
    numerator: TraceableField[float] | None,
    denominator: TraceableField[float] | None,
    expression: str,
    missing_reason: str,
    ratio_op: Callable[
        [str, TraceableField[float], TraceableField[float], str],
        TraceableField[float],
    ],
    missing_field_op: Callable[[str, str], TraceableField[float]],
) -> TraceableField[float]:
    if numerator is not None and denominator is not None:
        return ratio_op(name, numerator, denominator, expression)
    return missing_field_op(name, missing_reason)


def subtract(
    name: str,
    left: TraceableField[float],
    right: TraceableField[float],
    expression: str,
) -> TraceableField[float]:
    if left.value is None or right.value is None:
        return missing_field(name, f"Missing inputs for {expression}")
    value = float(left.value) - float(right.value)
    return computed_field(
        name=name,
        value=value,
        op_code="SUB",
        expression=expression,
        inputs={left.name: left, right.name: right},
    )


def repeat_rate(
    name: str,
    rate: TraceableField[float],
    count: int,
) -> TraceableField[list[float]]:
    if rate.value is None:
        return TraceableField(
            name=name,
            value=None,
            provenance=ManualProvenance(description=f"Missing base rate for {name}"),
        )
    values = [float(rate.value)] * count
    return computed_field(
        name=name,
        value=values,
        op_code="REPEAT",
        expression=f"Repeat {rate.name} for {count} years",
        inputs={rate.name: rate},
    )


def value_or_missing(
    tf: TraceableField[float] | None,
    field_name: str,
    missing: list[str],
) -> float | None:
    if tf is None or tf.value is None:
        missing.append(field_name)
        return None
    return float(tf.value)
