from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from statistics import median


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a rolling cohort stability report from release-gate snapshot artifacts."
        )
    )
    parser.add_argument(
        "--snapshots",
        type=Path,
        nargs="+",
        required=True,
        help="List of release-gate snapshot JSON paths.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output JSON path for the stability report.",
    )
    parser.add_argument(
        "--expected-profile",
        type=str,
        default="prod_cohort_v1",
        help="Expected gate profile for considered runs.",
    )
    parser.add_argument(
        "--window-size",
        type=int,
        default=2,
        help="Use the latest N runs for rolling stability decision.",
    )
    parser.add_argument(
        "--min-runs",
        type=int,
        default=2,
        help="Minimum considered runs required for stability decision.",
    )
    parser.add_argument("--max-consensus-gap-median-abs", type=float, default=0.15)
    parser.add_argument("--max-consensus-gap-p90-abs", type=float, default=0.60)
    parser.add_argument("--min-consensus-gap-count", type=int, default=20)
    parser.add_argument("--max-consensus-degraded-rate", type=float, default=0.80)
    parser.add_argument("--min-consensus-confidence-weight", type=float, default=0.30)
    parser.add_argument("--min-consensus-quality-count", type=int, default=20)
    parser.add_argument(
        "--min-replay-trace-contract-pass-rate", type=float, default=1.0
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    thresholds = _build_thresholds(args)

    run_rows: list[dict[str, object]] = []
    for snapshot_path in args.snapshots:
        run_rows.append(
            _build_run_row(snapshot_path, args.expected_profile, thresholds)
        )

    run_rows.sort(key=_run_sort_key)
    considered_runs = (
        run_rows[-args.window_size :] if args.window_size > 0 else run_rows
    )

    stable, reasons = _decide_stability(considered_runs, args.min_runs)

    report = {
        "generated_at": _utc_now_iso(),
        "expected_profile": args.expected_profile,
        "window_size": args.window_size,
        "min_runs": args.min_runs,
        "thresholds": thresholds,
        "input_count": len(run_rows),
        "considered_count": len(considered_runs),
        "runs": run_rows,
        "summary": _build_summary(considered_runs, stable, reasons),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _build_thresholds(args: argparse.Namespace) -> dict[str, float | int]:
    return {
        "max_consensus_gap_median_abs": args.max_consensus_gap_median_abs,
        "max_consensus_gap_p90_abs": args.max_consensus_gap_p90_abs,
        "min_consensus_gap_count": args.min_consensus_gap_count,
        "max_consensus_degraded_rate": args.max_consensus_degraded_rate,
        "min_consensus_confidence_weight": args.min_consensus_confidence_weight,
        "min_consensus_quality_count": args.min_consensus_quality_count,
        "min_replay_trace_contract_pass_rate": args.min_replay_trace_contract_pass_rate,
    }


def _build_run_row(
    snapshot_path: Path,
    expected_profile: str,
    thresholds: Mapping[str, float | int],
) -> dict[str, object]:
    payload = _read_json_mapping(snapshot_path)
    if payload is None:
        return {
            "snapshot_path": str(snapshot_path),
            "snapshot_available": False,
            "generated_at": None,
            "gate_profile": None,
            "release_gate_exit_code": None,
            "run_passed": False,
            "kpi_passed": False,
            "failed_checks": ["snapshot_unavailable_or_invalid"],
        }

    summary = _extract_mapping(payload.get("summary"))
    gap_distribution = _extract_mapping(summary.get("consensus_gap_distribution"))
    replay_checks = _extract_mapping(summary.get("replay_checks"))
    report_path_raw = payload.get("report_path")
    report_path = _resolve_report_path(snapshot_path, report_path_raw)
    quality_count = _extract_consensus_quality_count(report_path)

    generated_at = _extract_string(payload.get("generated_at"))
    gate_profile = _extract_string(payload.get("gate_profile"))
    release_gate_exit_code = _extract_int(payload.get("release_gate_exit_code"))

    gap_count = _extract_int(gap_distribution.get("available_count"))
    gap_median = _extract_float(gap_distribution.get("median"))
    gap_p90_abs = _extract_float(gap_distribution.get("p90_abs"))
    consensus_degraded_rate = _extract_float(summary.get("consensus_degraded_rate"))
    consensus_confidence_weight_avg = _extract_float(
        summary.get("consensus_confidence_weight_avg")
    )
    replay_trace_pass_rate = _extract_float(
        replay_checks.get("trace_contract_pass_rate")
    )

    checks: list[str] = []
    if gate_profile != expected_profile:
        checks.append("unexpected_profile")
    if release_gate_exit_code != 0:
        checks.append("release_gate_nonzero")
    if gap_count is None:
        checks.append("consensus_gap_count_missing")
    elif gap_count < _int_threshold(thresholds, "min_consensus_gap_count"):
        checks.append("consensus_gap_count_below_min")
    if gap_median is None:
        checks.append("consensus_gap_median_missing")
    elif abs(gap_median) > _float_threshold(thresholds, "max_consensus_gap_median_abs"):
        checks.append("consensus_gap_median_abs_above_max")
    if gap_p90_abs is None:
        checks.append("consensus_gap_p90_abs_missing")
    elif gap_p90_abs > _float_threshold(thresholds, "max_consensus_gap_p90_abs"):
        checks.append("consensus_gap_p90_abs_above_max")
    if consensus_degraded_rate is None:
        checks.append("consensus_degraded_rate_missing")
    elif consensus_degraded_rate > _float_threshold(
        thresholds, "max_consensus_degraded_rate"
    ):
        checks.append("consensus_degraded_rate_above_max")
    if consensus_confidence_weight_avg is None:
        checks.append("consensus_confidence_weight_avg_missing")
    elif consensus_confidence_weight_avg < _float_threshold(
        thresholds, "min_consensus_confidence_weight"
    ):
        checks.append("consensus_confidence_weight_avg_below_min")
    if quality_count is None:
        checks.append("consensus_quality_count_missing")
    elif quality_count < _int_threshold(thresholds, "min_consensus_quality_count"):
        checks.append("consensus_quality_count_below_min")
    if replay_trace_pass_rate is None:
        checks.append("replay_trace_contract_pass_rate_missing")
    elif replay_trace_pass_rate < _float_threshold(
        thresholds, "min_replay_trace_contract_pass_rate"
    ):
        checks.append("replay_trace_contract_pass_rate_below_min")

    run_passed = release_gate_exit_code == 0
    return {
        "snapshot_path": str(snapshot_path),
        "snapshot_available": True,
        "generated_at": generated_at,
        "gate_profile": gate_profile,
        "release_gate_exit_code": release_gate_exit_code,
        "run_passed": run_passed,
        "kpi_passed": len(checks) == 0,
        "failed_checks": checks,
        "report_path": str(report_path) if report_path is not None else None,
        "consensus_gap_count": gap_count,
        "consensus_gap_median": gap_median,
        "consensus_gap_p90_abs": gap_p90_abs,
        "consensus_degraded_rate": consensus_degraded_rate,
        "consensus_confidence_weight_avg": consensus_confidence_weight_avg,
        "consensus_quality_count": quality_count,
        "replay_trace_contract_pass_rate": replay_trace_pass_rate,
    }


def _decide_stability(
    considered_runs: Sequence[Mapping[str, object]],
    min_runs: int,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if len(considered_runs) < min_runs:
        reasons.append("insufficient_runs")
    failing_ids = [
        str(run.get("snapshot_path"))
        for run in considered_runs
        if run.get("kpi_passed") is not True
    ]
    if failing_ids:
        reasons.append("kpi_failures_present")
    return len(reasons) == 0, reasons


def _build_summary(
    considered_runs: Sequence[Mapping[str, object]],
    stable: bool,
    reasons: Sequence[str],
) -> dict[str, object]:
    run_passed_count = 0
    kpi_passed_count = 0
    medians: list[float] = []
    p90_values: list[float] = []
    quality_counts: list[int] = []
    gap_counts: list[int] = []

    for run in considered_runs:
        if run.get("run_passed") is True:
            run_passed_count += 1
        if run.get("kpi_passed") is True:
            kpi_passed_count += 1
        gap_median = run.get("consensus_gap_median")
        if isinstance(gap_median, float):
            medians.append(abs(gap_median))
        p90_abs = run.get("consensus_gap_p90_abs")
        if isinstance(p90_abs, float):
            p90_values.append(p90_abs)
        quality_count = run.get("consensus_quality_count")
        if isinstance(quality_count, int):
            quality_counts.append(quality_count)
        gap_count = run.get("consensus_gap_count")
        if isinstance(gap_count, int):
            gap_counts.append(gap_count)

    considered_count = len(considered_runs)
    return {
        "considered_runs": considered_count,
        "run_passed_count": run_passed_count,
        "kpi_passed_count": kpi_passed_count,
        "run_pass_rate": _safe_ratio(run_passed_count, considered_count),
        "kpi_pass_rate": _safe_ratio(kpi_passed_count, considered_count),
        "median_abs_consensus_gap_median": median(medians) if medians else None,
        "median_consensus_gap_p90_abs": median(p90_values) if p90_values else None,
        "min_consensus_quality_count": min(quality_counts) if quality_counts else None,
        "min_consensus_gap_count": min(gap_counts) if gap_counts else None,
        "latest_snapshot_path": _extract_latest_path(considered_runs),
        "stable": stable,
        "stability_reasons": list(reasons),
    }


def _extract_latest_path(considered_runs: Sequence[Mapping[str, object]]) -> str | None:
    if not considered_runs:
        return None
    latest = considered_runs[-1]
    value = latest.get("snapshot_path")
    if isinstance(value, str) and value:
        return value
    return None


def _run_sort_key(run: Mapping[str, object]) -> tuple[int, str]:
    generated_at = run.get("generated_at")
    if isinstance(generated_at, str) and generated_at:
        parsed = _parse_datetime(generated_at)
        if parsed is not None:
            return (int(parsed.timestamp()), str(run.get("snapshot_path")))
    return (0, str(run.get("snapshot_path")))


def _extract_consensus_quality_count(report_path: Path | None) -> int | None:
    payload = _read_json_mapping(report_path)
    if payload is None:
        return None
    summary = _extract_mapping(payload.get("summary"))
    quality = _extract_mapping(summary.get("consensus_quality_distribution"))
    return _extract_int(quality.get("available_count"))


def _resolve_report_path(snapshot_path: Path, raw_report_path: object) -> Path | None:
    report_path_str = _extract_string(raw_report_path)
    if report_path_str is None:
        return None
    report_path = Path(report_path_str)
    if report_path.is_absolute():
        return report_path
    candidates = (
        snapshot_path.parent / report_path,
        snapshot_path.parent.parent / report_path,
        Path.cwd() / report_path,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[1]


def _read_json_mapping(path: Path | None) -> Mapping[str, object] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(payload, Mapping):
        return payload
    return None


def _extract_mapping(value: object) -> Mapping[str, object]:
    if isinstance(value, Mapping):
        return value
    return {}


def _extract_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _extract_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _extract_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        return float(value)
    return None


def _int_threshold(thresholds: Mapping[str, float | int], key: str) -> int:
    value = thresholds.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    raise ValueError(f"threshold_missing:{key}")


def _float_threshold(thresholds: Mapping[str, float | int], key: str) -> float:
    value = thresholds.get(key)
    if isinstance(value, int):
        return float(value)
    if isinstance(value, float):
        return float(value)
    raise ValueError(f"threshold_missing:{key}")


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _parse_datetime(value: str) -> datetime | None:
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
