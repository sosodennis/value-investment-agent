from __future__ import annotations

from collections.abc import Mapping, Sequence

from src.shared.kernel.types import JSONObject

from ..valuation_model_registry import ValuationModelRegistry
from .contracts import BacktestCase, CaseResult
from .io_service import coerce_mapping


def run_backtest_cases(cases: Sequence[BacktestCase]) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        model_runtime = ValuationModelRegistry.get_model_runtime(case.model)
        if not isinstance(model_runtime, Mapping):
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    model=case.model,
                    status="error",
                    error=f"Unknown valuation model: {case.model}",
                )
            )
            continue

        schema_raw = model_runtime.get("schema")
        calculator_raw = model_runtime.get("calculator")
        if not callable(schema_raw) or not callable(calculator_raw):
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    model=case.model,
                    status="error",
                    error=f"Incomplete model runtime for model: {case.model}",
                )
            )
            continue

        try:
            params_obj = schema_raw(**case.params)
            raw_result = calculator_raw(params_obj)
            result_mapping = coerce_mapping(
                raw_result, f"calculation result for case '{case.case_id}'"
            )

            error_raw = result_mapping.get("error")
            if isinstance(error_raw, str) and error_raw:
                results.append(
                    CaseResult(
                        case_id=case.case_id,
                        model=case.model,
                        status="error",
                        error=error_raw,
                    )
                )
                continue

            metrics = extract_backtest_metrics(result_mapping)
            missing_required = [
                metric
                for metric in case.required_metrics
                if _lookup_numeric_metric(metrics, metric) is None
            ]
            if missing_required:
                results.append(
                    CaseResult(
                        case_id=case.case_id,
                        model=case.model,
                        status="error",
                        error="Missing required metrics: "
                        + ", ".join(sorted(missing_required)),
                    )
                )
                continue

            results.append(
                CaseResult(
                    case_id=case.case_id,
                    model=case.model,
                    status="ok",
                    metrics=metrics,
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    model=case.model,
                    status="error",
                    error=str(exc),
                )
            )
    return results


def extract_backtest_metrics(result: Mapping[str, object]) -> JSONObject:
    metrics: JSONObject = {}
    for key in (
        "intrinsic_value",
        "equity_value",
        "enterprise_value",
        "cost_of_equity",
        "upside_potential",
    ):
        value = result.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            metrics[key] = float(value)

    details_raw = result.get("details")
    if isinstance(details_raw, Mapping):
        distribution_raw = details_raw.get("distribution_summary")
        if isinstance(distribution_raw, Mapping):
            summary_raw = distribution_raw.get("summary")
            if isinstance(summary_raw, Mapping):
                summary: JSONObject = {}
                for key, value in summary_raw.items():
                    if isinstance(value, int | float) and not isinstance(value, bool):
                        summary[str(key)] = float(value)
                if summary:
                    metrics["distribution_summary"] = summary

    return metrics


def _lookup_numeric_metric(payload: Mapping[str, object], path: str) -> float | None:
    current: object = payload
    for key in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    if isinstance(current, int | float) and not isinstance(current, bool):
        return float(current)
    return None
