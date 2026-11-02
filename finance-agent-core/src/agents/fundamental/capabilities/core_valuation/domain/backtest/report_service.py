from __future__ import annotations

from collections.abc import Mapping, Sequence
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
    calibration: JSONObject | None = None,
) -> JSONObject:
    ok_count = sum(1 for item in results if item.status == "ok")
    error_count = sum(1 for item in results if item.status == "error")
    drifted_cases = {item.case_id for item in drifts}
    upside_values = _collect_upside_values(results)
    guardrail_hits = _collect_guardrail_hits(results)
    reinvestment_guardrail_hits = _collect_reinvestment_guardrail_hits(results)
    shares_scope_mismatch_flags = _collect_shares_scope_mismatch_flags(results)
    consensus_gaps = _collect_consensus_gaps(results)
    consensus_confidence_weights = _collect_consensus_confidence_weights(results)
    consensus_quality_buckets = _collect_consensus_quality_buckets(results)
    consensus_warning_code_sets = _collect_consensus_warning_code_sets(results)
    consensus_quality_distribution = _build_consensus_quality_distribution(
        consensus_quality_buckets
    )
    consensus_warning_code_distribution = _build_consensus_warning_code_distribution(
        consensus_warning_code_sets
    )

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

    calibration_gate_passed = True
    if calibration is not None:
        gate_value = calibration.get("gate_passed")
        calibration_gate_passed = isinstance(gate_value, bool) and gate_value

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
            "calibration_gate_passed": calibration_gate_passed,
            "extreme_upside_rate": _compute_extreme_upside_rate(upside_values),
            "guardrail_hit_rate": _compute_guardrail_hit_rate(guardrail_hits),
            "reinvestment_guardrail_hit_rate": _compute_guardrail_hit_rate(
                reinvestment_guardrail_hits
            ),
            "shares_scope_mismatch_rate": _compute_guardrail_hit_rate(
                shares_scope_mismatch_flags
            ),
            "consensus_gap_distribution": _build_consensus_gap_distribution(
                consensus_gaps
            ),
            "consensus_confidence_weight_avg": _compute_mean(
                consensus_confidence_weights
            ),
            "consensus_degraded_rate": _read_numeric(
                consensus_quality_distribution, "degraded_rate"
            )
            or 0.0,
            "consensus_quality_distribution": consensus_quality_distribution,
            "consensus_warning_code_distribution": consensus_warning_code_distribution,
            "consensus_provider_blocked_rate": _extract_warning_code_rate(
                distribution=consensus_warning_code_distribution,
                code="provider_blocked",
            ),
            "consensus_parse_missing_rate": _extract_warning_code_rate(
                distribution=consensus_warning_code_distribution,
                code="provider_parse_missing",
            ),
        },
        "calibration": calibration or {},
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


def _collect_upside_values(results: Sequence[CaseResult]) -> list[float]:
    output: list[float] = []
    for item in results:
        if item.status != "ok" or item.metrics is None:
            continue
        upside = _read_numeric(item.metrics, "upside_potential")
        if upside is not None:
            output.append(upside)
    return output


def _collect_guardrail_hits(results: Sequence[CaseResult]) -> list[bool]:
    output: list[bool] = []
    for item in results:
        if item.status != "ok" or item.metrics is None:
            continue
        guardrail_hit = _extract_guardrail_hit(item.metrics)
        if guardrail_hit is not None:
            output.append(guardrail_hit)
    return output


def _collect_reinvestment_guardrail_hits(results: Sequence[CaseResult]) -> list[bool]:
    output: list[bool] = []
    for item in results:
        if item.status != "ok" or item.metrics is None:
            continue
        capex = _coerce_bool_like(item.metrics.get("base_capex_guardrail_applied"))
        wc = _coerce_bool_like(item.metrics.get("base_wc_guardrail_applied"))
        flags = [flag for flag in (capex, wc) if flag is not None]
        if not flags:
            continue
        output.append(any(flags))
    return output


def _collect_shares_scope_mismatch_flags(results: Sequence[CaseResult]) -> list[bool]:
    output: list[bool] = []
    for item in results:
        if item.status != "ok" or item.metrics is None:
            continue
        mismatch_detected = _coerce_bool_like(
            item.metrics.get("shares_scope_mismatch_detected")
        )
        mismatch_resolved = _coerce_bool_like(
            item.metrics.get("shares_scope_mismatch_resolved")
        )
        if mismatch_detected is None:
            continue
        output.append(mismatch_detected and not bool(mismatch_resolved))
    return output


def _collect_consensus_gaps(results: Sequence[CaseResult]) -> list[float]:
    output: list[float] = []
    for item in results:
        if item.status != "ok" or item.metrics is None:
            continue
        consensus_gap = _extract_consensus_gap(item.metrics)
        if consensus_gap is not None:
            output.append(consensus_gap)
    return output


def _collect_consensus_confidence_weights(results: Sequence[CaseResult]) -> list[float]:
    output: list[float] = []
    for item in results:
        if item.status != "ok" or item.metrics is None:
            continue
        weight = _read_numeric(item.metrics, "target_consensus_confidence_weight")
        if weight is not None:
            output.append(weight)
    return output


def _collect_consensus_quality_buckets(results: Sequence[CaseResult]) -> list[str]:
    output: list[str] = []
    for item in results:
        if item.status != "ok" or item.metrics is None:
            continue
        bucket = item.metrics.get("target_consensus_quality_bucket")
        if isinstance(bucket, str) and bucket in {"high", "medium", "low", "degraded"}:
            output.append(bucket)
    return output


def _collect_consensus_warning_code_sets(
    results: Sequence[CaseResult],
) -> list[set[str]]:
    output: list[set[str]] = []
    for item in results:
        if item.status != "ok" or item.metrics is None:
            continue
        raw_codes = item.metrics.get("target_consensus_warning_codes")
        if not isinstance(raw_codes, list):
            continue
        parsed_codes = {
            code for code in raw_codes if isinstance(code, str) and code.strip()
        }
        if parsed_codes:
            output.append(parsed_codes)
    return output


def _extract_guardrail_hit(metrics: Mapping[str, object]) -> bool | None:
    direct = _coerce_bool_like(metrics.get("guardrail_hit"))
    if direct is not None:
        return direct

    flags: list[bool] = []
    for key in ("base_growth_guardrail_applied", "base_margin_guardrail_applied"):
        parsed = _coerce_bool_like(metrics.get(key))
        if parsed is not None:
            flags.append(parsed)
    for key in ("base_capex_guardrail_applied", "base_wc_guardrail_applied"):
        parsed = _coerce_bool_like(metrics.get(key))
        if parsed is not None:
            flags.append(parsed)
    if flags:
        return any(flags)
    return None


def _extract_consensus_gap(metrics: Mapping[str, object]) -> float | None:
    for path in (
        "consensus_gap_pct",
        "consensus_gap_ratio",
        "consensus_gap",
        "consensus.gap_pct",
        "consensus.gap_ratio",
    ):
        value = _read_numeric(metrics, path)
        if value is not None:
            return value

    intrinsic_value = _read_numeric(metrics, "intrinsic_value")
    if intrinsic_value is None:
        return None
    for path in (
        "consensus_target_price_median",
        "consensus_price_median",
        "target_price_median",
        "consensus.target_price_median",
    ):
        target = _read_numeric(metrics, path)
        if target is not None and abs(target) > 1e-12:
            return (intrinsic_value - target) / abs(target)
    return None


def _compute_extreme_upside_rate(upside_values: Sequence[float]) -> float:
    if not upside_values:
        return 0.0
    extreme_count = sum(1 for value in upside_values if value > 0.8)
    return extreme_count / len(upside_values)


def _compute_guardrail_hit_rate(guardrail_hits: Sequence[bool]) -> float:
    if not guardrail_hits:
        return 0.0
    hit_count = sum(1 for value in guardrail_hits if value)
    return hit_count / len(guardrail_hits)


def _compute_mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _build_consensus_quality_distribution(
    buckets: Sequence[str],
) -> JSONObject:
    if not buckets:
        return {"available_count": 0}

    high_count = sum(1 for bucket in buckets if bucket == "high")
    medium_count = sum(1 for bucket in buckets if bucket == "medium")
    low_count = sum(1 for bucket in buckets if bucket == "low")
    degraded_count = sum(1 for bucket in buckets if bucket == "degraded")
    total = len(buckets)
    return {
        "available_count": total,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "degraded_count": degraded_count,
        "high_rate": high_count / total,
        "medium_rate": medium_count / total,
        "low_rate": low_count / total,
        "degraded_rate": degraded_count / total,
    }


def _build_consensus_warning_code_distribution(
    code_sets: Sequence[set[str]],
) -> JSONObject:
    if not code_sets:
        return {"available_count": 0}

    code_case_counts: dict[str, int] = {}
    for codes in code_sets:
        for code in codes:
            code_case_counts[code] = code_case_counts.get(code, 0) + 1

    available_count = len(code_sets)
    code_case_rates = {
        code: count / available_count
        for code, count in sorted(code_case_counts.items())
    }
    return {
        "available_count": available_count,
        "code_case_counts": dict(sorted(code_case_counts.items())),
        "code_case_rates": code_case_rates,
    }


def _extract_warning_code_rate(
    *,
    distribution: Mapping[str, object],
    code: str,
) -> float:
    rates_raw = distribution.get("code_case_rates")
    if not isinstance(rates_raw, Mapping):
        return 0.0
    rate_raw = rates_raw.get(code)
    if isinstance(rate_raw, int | float) and not isinstance(rate_raw, bool):
        return float(rate_raw)
    return 0.0


def _build_consensus_gap_distribution(consensus_gaps: Sequence[float]) -> JSONObject:
    if not consensus_gaps:
        return {"available_count": 0}

    values = sorted(float(value) for value in consensus_gaps)
    absolute_values = sorted(abs(value) for value in values)
    count = len(values)
    mean = sum(values) / count
    mean_abs = sum(abs(value) for value in values) / count
    return {
        "available_count": count,
        "median": _percentile(values, 50.0),
        "p10": _percentile(values, 10.0),
        "p90": _percentile(values, 90.0),
        "mean": mean,
        "mean_abs": mean_abs,
        "p90_abs": _percentile(absolute_values, 90.0),
        "max_abs": max(abs(value) for value in values),
    }


def _read_numeric(payload: Mapping[str, object], path: str) -> float | None:
    current: object = payload
    for key in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    if isinstance(current, int | float) and not isinstance(current, bool):
        return float(current)
    return None


def _coerce_bool_like(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        if value == 1:
            return True
        if value == 0:
            return False
    return None


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("sorted_values must not be empty")
    if len(sorted_values) == 1:
        return sorted_values[0]

    rank = (q / 100.0) * (len(sorted_values) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return (sorted_values[lower] * (1.0 - weight)) + (sorted_values[upper] * weight)
