from __future__ import annotations

from collections.abc import Iterable

from .contracts import GovernanceDrift


def compare_registry_payloads(
    *,
    baseline: dict[str, object],
    current: dict[str, object],
) -> tuple[list[GovernanceDrift], list[str]]:
    drifts: list[GovernanceDrift] = []
    _diff_payloads("", baseline, current, drifts)
    issues: list[str] = []
    if drifts:
        issues.append("governance_registry_drift_detected")
    return drifts, issues


def _diff_payloads(
    path: str,
    baseline: object,
    current: object,
    drifts: list[GovernanceDrift],
) -> None:
    if isinstance(baseline, dict) and isinstance(current, dict):
        keys = set(baseline.keys()) | set(current.keys())
        for key in sorted(keys):
            next_path = f"{path}.{key}" if path else key
            _diff_payloads(next_path, baseline.get(key), current.get(key), drifts)
        return
    if isinstance(baseline, list) and isinstance(current, list):
        _diff_lists(path, baseline, current, drifts)
        return
    if baseline != current:
        drifts.append(GovernanceDrift(path=path, expected=baseline, actual=current))


def _diff_lists(
    path: str,
    baseline: list[object],
    current: list[object],
    drifts: list[GovernanceDrift],
) -> None:
    if len(baseline) != len(current):
        drifts.append(
            GovernanceDrift(
                path=f"{path}.length" if path else "length",
                expected=len(baseline),
                actual=len(current),
            )
        )
    for index, (left, right) in enumerate(_zip_longest(baseline, current)):
        next_path = f"{path}[{index}]" if path else f"[{index}]"
        _diff_payloads(next_path, left, right, drifts)


def _zip_longest(
    left: list[object], right: list[object]
) -> Iterable[tuple[object, object]]:
    max_len = max(len(left), len(right))
    for idx in range(max_len):
        yield (
            left[idx] if idx < len(left) else None,
            right[idx] if idx < len(right) else None,
        )


__all__ = [
    "compare_registry_payloads",
]
