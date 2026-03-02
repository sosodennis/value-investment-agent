from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from src.shared.kernel.types import JSONObject

from .contracts import CaseResult, MetricDrift


def build_backtest_baseline_payload(results: Sequence[CaseResult]) -> JSONObject:
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


def build_backtest_report_payload(
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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
