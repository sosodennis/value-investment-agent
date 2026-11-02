from __future__ import annotations

from collections.abc import Mapping, Sequence

from .contracts import BacktestConfig, BaselineCase, CaseResult, MetricDrift


def compare_backtest_results_with_baseline(
    results: Sequence[CaseResult],
    baseline_cases: Mapping[str, BaselineCase],
    *,
    config: BacktestConfig,
) -> tuple[list[MetricDrift], list[str]]:
    drifts: list[MetricDrift] = []
    issues: list[str] = []

    for result in results:
        if result.status != "ok":
            continue
        if result.metrics is None:
            issues.append(f"{result.case_id}: metrics missing for successful run")
            continue

        baseline_case = baseline_cases.get(result.case_id)
        if baseline_case is None:
            issues.append(f"{result.case_id}: missing baseline case")
            continue
        if baseline_case.model != result.model:
            issues.append(
                f"{result.case_id}: baseline model mismatch "
                f"({baseline_case.model} vs {result.model})"
            )
            continue

        baseline_metrics = _flatten_numeric_metrics(baseline_case.metrics)
        current_metrics = _flatten_numeric_metrics(result.metrics)

        for path, baseline_value in baseline_metrics.items():
            current_value = current_metrics.get(path)
            if current_value is None:
                issues.append(f"{result.case_id}: missing metric path '{path}'")
                continue
            abs_diff = abs(current_value - baseline_value)
            rel_diff = abs_diff / max(abs(baseline_value), 1e-12)
            if abs_diff > config.abs_tol and rel_diff > config.rel_tol:
                drifts.append(
                    MetricDrift(
                        case_id=result.case_id,
                        metric_path=path,
                        baseline=baseline_value,
                        current=current_value,
                        abs_diff=abs_diff,
                        rel_diff=rel_diff,
                    )
                )

    return drifts, issues


def _flatten_numeric_metrics(
    payload: Mapping[str, object],
    *,
    prefix: str = "",
) -> dict[str, float]:
    output: dict[str, float] = {}
    for key, value in payload.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            output.update(_flatten_numeric_metrics(value, prefix=path))
            continue
        if isinstance(value, int | float) and not isinstance(value, bool):
            output[path] = float(value)
    return output
