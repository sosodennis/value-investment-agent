from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.shared.kernel.types import JSONObject

from .registry import SkillRegistry


@dataclass(frozen=True)
class BacktestConfig:
    abs_tol: float = 1e-6
    rel_tol: float = 1e-4


@dataclass(frozen=True)
class BacktestCase:
    case_id: str
    model: str
    params: JSONObject
    required_metrics: tuple[str, ...]


@dataclass(frozen=True)
class MetricDrift:
    case_id: str
    metric_path: str
    baseline: float
    current: float
    abs_diff: float
    rel_diff: float


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    model: str
    status: str
    metrics: JSONObject | None = None
    error: str | None = None


@dataclass(frozen=True)
class BaselineCase:
    model: str
    metrics: JSONObject


def load_cases(path: Path) -> list[BacktestCase]:
    payload = _read_json_object(path, context="backtest dataset")
    raw_cases = _as_sequence(payload.get("cases"), "backtest dataset.cases")

    cases: list[BacktestCase] = []
    for index, item in enumerate(raw_cases):
        context = f"backtest dataset.cases[{index}]"
        mapping = _as_mapping(item, context)
        case_id = _as_string(mapping.get("id"), f"{context}.id")
        model = _as_string(mapping.get("model"), f"{context}.model")
        params = _as_json_object(mapping.get("params"), f"{context}.params")

        required_metrics_raw = mapping.get("required_metrics")
        required_metrics: tuple[str, ...] = ()
        if required_metrics_raw is not None:
            required_metrics = tuple(
                _as_string(value, f"{context}.required_metrics[{i}]")
                for i, value in enumerate(
                    _as_sequence(required_metrics_raw, f"{context}.required_metrics")
                )
            )

        cases.append(
            BacktestCase(
                case_id=case_id,
                model=model,
                params=params,
                required_metrics=required_metrics,
            )
        )
    return cases


def load_baseline(path: Path) -> dict[str, BaselineCase]:
    payload = _read_json_object(path, context="backtest baseline")
    raw_cases = _as_mapping(payload.get("cases"), "backtest baseline.cases")

    baseline: dict[str, BaselineCase] = {}
    for case_id, raw_case in raw_cases.items():
        context = f"backtest baseline.cases.{case_id}"
        mapping = _as_mapping(raw_case, context)
        model = _as_string(mapping.get("model"), f"{context}.model")
        metrics = _as_json_object(mapping.get("metrics"), f"{context}.metrics")
        baseline[case_id] = BaselineCase(model=model, metrics=metrics)
    return baseline


def run_cases(cases: Sequence[BacktestCase]) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        skill = SkillRegistry.get_skill(case.model)
        if not isinstance(skill, Mapping):
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    model=case.model,
                    status="error",
                    error=f"Unknown valuation model: {case.model}",
                )
            )
            continue

        schema_raw = skill.get("schema")
        calculator_raw = skill.get("calculator")
        if not callable(schema_raw) or not callable(calculator_raw):
            results.append(
                CaseResult(
                    case_id=case.case_id,
                    model=case.model,
                    status="error",
                    error=f"Incomplete skill runtime for model: {case.model}",
                )
            )
            continue

        try:
            schema = schema_raw
            calculator = calculator_raw
            params_obj = schema(**case.params)
            raw_result = calculator(params_obj)
            result_mapping = _as_mapping(
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

            metrics = _extract_metrics(result_mapping)
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
                        error=(
                            "Missing required metrics: "
                            + ", ".join(sorted(missing_required))
                        ),
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


def compare_with_baseline(
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


def build_baseline_payload(results: Sequence[CaseResult]) -> JSONObject:
    cases: JSONObject = {}
    for result in results:
        if result.status != "ok" or result.metrics is None:
            continue
        cases[result.case_id] = {
            "model": result.model,
            "metrics": result.metrics,
        }
    return {
        "generated_at": _utc_now_iso(),
        "cases": cases,
    }


def build_report_payload(
    *,
    dataset_path: Path,
    baseline_path: Path,
    results: Sequence[CaseResult],
    drifts: Sequence[MetricDrift],
    issues: Sequence[str],
    baseline_updated: bool,
) -> JSONObject:
    ok_count = sum(1 for item in results if item.status == "ok")
    error_count = sum(1 for item in results if item.status == "error")
    drifted_cases = {item.case_id for item in drifts}

    serialized_results: list[JSONObject] = []
    for item in results:
        payload: JSONObject = {
            "id": item.case_id,
            "model": item.model,
            "status": item.status,
        }
        if item.metrics is not None:
            payload["metrics"] = item.metrics
        if item.error is not None:
            payload["error"] = item.error
        serialized_results.append(payload)

    return {
        "generated_at": _utc_now_iso(),
        "dataset_path": str(dataset_path),
        "baseline_path": str(baseline_path),
        "summary": {
            "total_cases": len(results),
            "ok": ok_count,
            "errors": error_count,
            "drift_count": len(drifts),
            "drifted_case_count": len(drifted_cases),
            "issue_count": len(issues),
            "baseline_updated": baseline_updated,
        },
        "results": serialized_results,
        "drifts": [
            {
                "case_id": item.case_id,
                "metric_path": item.metric_path,
                "baseline": item.baseline,
                "current": item.current,
                "abs_diff": item.abs_diff,
                "rel_diff": item.rel_diff,
            }
            for item in drifts
        ],
        "issues": list(issues),
    }


def _extract_metrics(result: Mapping[str, object]) -> JSONObject:
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


def _lookup_numeric_metric(payload: Mapping[str, object], path: str) -> float | None:
    current: object = payload
    for key in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    if isinstance(current, int | float) and not isinstance(current, bool):
        return float(current)
    return None


def _read_json_object(path: Path, *, context: str) -> JSONObject:
    raw = path.read_text(encoding="utf-8")
    import json

    parsed = json.loads(raw)
    return _as_json_object(parsed, context)


def _as_mapping(value: object, context: str) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    raise TypeError(f"{context} must be an object")


def _as_json_object(value: object, context: str) -> JSONObject:
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError(f"{context} must be a JSON object")


def _as_sequence(value: object, context: str) -> Sequence[object]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return value
    raise TypeError(f"{context} must be an array")


def _as_string(value: object, context: str) -> str:
    if isinstance(value, str) and value:
        return value
    raise TypeError(f"{context} must be a non-empty string")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
