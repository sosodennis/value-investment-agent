from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
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


@dataclass(frozen=True)
class MissingMetricPolicyDecision:
    blocking_fields: list[str]
    warn_only_fields: list[str]


def apply_missing_metric_policy(
    *,
    missing_fields: Iterable[str],
    warn_only_fields: Iterable[str],
) -> MissingMetricPolicyDecision:
    warn_only_set = {item for item in warn_only_fields if item}
    blocking: list[str] = []
    warn_only: list[str] = []
    for field_name in missing_fields:
        if not field_name:
            continue
        if field_name in warn_only_set:
            warn_only.append(field_name)
            continue
        blocking.append(field_name)
    return MissingMetricPolicyDecision(
        blocking_fields=blocking,
        warn_only_fields=warn_only,
    )
