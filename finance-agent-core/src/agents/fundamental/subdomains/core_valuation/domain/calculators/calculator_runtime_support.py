from __future__ import annotations

from src.agents.fundamental.domain.shared.contracts.traceable import TraceableField
from src.agents.fundamental.subdomains.core_valuation.domain.parameterization.types import (
    TraceInput,
)


def unwrap_traceable_value(
    value: float | list[float] | TraceableField,
) -> float | list[float]:
    if isinstance(value, TraceableField):
        inner = value.value
        if inner is None:
            raise ValueError("TraceableField value is None")
        if isinstance(inner, list):
            return [float(v) for v in inner]
        return float(inner)
    if isinstance(value, list):
        return [float(v) for v in value]
    return float(value)


def apply_trace_inputs(
    inputs: dict[str, object],
    trace_inputs: dict[str, TraceInput],
) -> dict[str, object]:
    if not trace_inputs:
        return inputs
    merged = inputs.copy()
    for key, value in trace_inputs.items():
        if key in merged and value is not None:
            merged[key] = value
    return merged


def compute_upside(intrinsic_value: float, current_price: float | None) -> float:
    if current_price is None or current_price <= 0:
        return 0.0
    return (intrinsic_value - current_price) / current_price
