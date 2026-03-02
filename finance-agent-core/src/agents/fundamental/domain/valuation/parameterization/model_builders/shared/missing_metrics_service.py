from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Protocol


class _SupportsValue(Protocol):
    value: object | None


def collect_missing_metric_names(
    *,
    metric_fields: Mapping[str, _SupportsValue | None],
) -> list[str]:
    missing: list[str] = []
    for field_name, trace_field in metric_fields.items():
        if trace_field is None or trace_field.value is None:
            missing.append(field_name)
    return missing


def extend_missing_fields(*, missing: list[str], field_names: Iterable[str]) -> None:
    missing.extend(field_names)
