from __future__ import annotations


def traceable_value(field: object) -> object | None:
    if field is None:
        return None
    if isinstance(field, dict):
        return field.get("value")
    return field


def to_number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int | float):
        return None
    return float(value)


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0.0:
        return None
    return numerator / denominator


def calculate_cagr(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    latest = values[0]
    earliest = values[-1]
    if latest <= 0 or earliest <= 0:
        return None
    years = len(values) - 1
    return (latest / earliest) ** (1 / years) - 1
