from __future__ import annotations

from math import sqrt

from src.shared.kernel.traceable import (
    ComputedProvenance,
    ManualProvenance,
    TraceableField,
)


def computed_field(
    name: str,
    value: float | list[float],
    op_code: str,
    expression: str,
    inputs: dict[str, TraceableField],
) -> TraceableField:
    return TraceableField(
        name=name,
        value=value,
        provenance=ComputedProvenance(
            op_code=op_code,
            expression=expression,
            inputs=inputs,
        ),
    )


def growth_rates_from_series(
    name: str,
    series: list[TraceableField[float]],
    count: int,
) -> TraceableField[list[float]]:
    values: list[float] = []
    inputs: dict[str, TraceableField] = {}

    for idx in range(len(series) - 1):
        current = series[idx]
        previous = series[idx + 1]
        inputs[f"{current.name} (t-{idx})"] = current
        inputs[f"{previous.name} (t-{idx + 1})"] = previous
        if current.value is None or previous.value in (None, 0):
            continue
        values.append(float(current.value) / float(previous.value) - 1.0)

    if not values:
        return TraceableField(
            name=name,
            value=None,
            provenance=ManualProvenance(description="Insufficient history for growth"),
        )

    avg_growth = sum(values) / len(values)
    projected = [avg_growth] * count
    return computed_field(
        name=name,
        value=projected,
        op_code="YOY_GROWTH_AVG",
        expression="Average historical YoY growth (SEC XBRL)",
        inputs=inputs,
    )


def growth_observations_from_series(
    series: list[TraceableField[float]],
) -> list[float]:
    values: list[float] = []
    for idx in range(len(series) - 1):
        current = series[idx]
        previous = series[idx + 1]
        if current.value is None or previous.value in (None, 0):
            continue
        values.append(float(current.value) / float(previous.value) - 1.0)
    return values


def population_stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return sqrt(variance)


def dedupe_missing(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
