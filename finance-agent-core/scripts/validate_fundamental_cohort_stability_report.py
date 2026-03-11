from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate fundamental rolling cohort stability report artifact.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Path to cohort stability report JSON.",
    )
    parser.add_argument(
        "--require-stable",
        action="store_true",
        help="Require summary.stable=true.",
    )
    parser.add_argument(
        "--min-considered-runs",
        type=int,
        default=0,
        help="Require summary.considered_runs to be >= this threshold.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = _read_payload(args.path)
    issues = _validate_payload(payload)

    summary_raw = payload.get("summary")
    summary = summary_raw if isinstance(summary_raw, Mapping) else {}

    if args.require_stable:
        if summary.get("stable") is not True:
            issues.append("summary.stable_required_but_false")
    considered_runs = summary.get("considered_runs")
    if args.min_considered_runs > 0:
        if not _is_int(considered_runs):
            issues.append("summary.considered_runs_missing_or_invalid")
        elif int(considered_runs) < args.min_considered_runs:
            issues.append("summary.considered_runs_below_min")

    output = {
        "path": str(args.path),
        "gate_passed": len(issues) == 0,
        "issues": issues,
    }
    print(json.dumps(output, ensure_ascii=False))
    if issues:
        return 1
    return 0


def _read_payload(path: Path) -> Mapping[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, Mapping):
        raise TypeError("stability report root must be an object")
    return parsed


def _validate_payload(payload: Mapping[str, object]) -> list[str]:
    issues: list[str] = []
    if not _is_non_empty_text(payload.get("generated_at")):
        issues.append("generated_at_missing_or_invalid")
    if not _is_non_empty_text(payload.get("expected_profile")):
        issues.append("expected_profile_missing_or_invalid")
    if not _is_int(payload.get("window_size")):
        issues.append("window_size_missing_or_invalid")
    if not _is_int(payload.get("min_runs")):
        issues.append("min_runs_missing_or_invalid")
    if not _is_int(payload.get("input_count")):
        issues.append("input_count_missing_or_invalid")
    if not _is_int(payload.get("considered_count")):
        issues.append("considered_count_missing_or_invalid")

    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, Mapping):
        issues.append("thresholds_missing_or_invalid")

    runs = payload.get("runs")
    if not isinstance(runs, Sequence) or isinstance(runs, str | bytes):
        issues.append("runs_missing_or_invalid")
    else:
        issues.extend(_validate_runs(runs))

    summary = payload.get("summary")
    if not isinstance(summary, Mapping):
        issues.append("summary_missing_or_invalid")
    else:
        issues.extend(_validate_summary(summary))
    return issues


def _validate_runs(runs: Sequence[object]) -> list[str]:
    issues: list[str] = []
    for index, item in enumerate(runs):
        if not isinstance(item, Mapping):
            issues.append(f"runs[{index}]_missing_or_invalid")
            continue
        if not _is_non_empty_text(item.get("snapshot_path")):
            issues.append(f"runs[{index}].snapshot_path_missing_or_invalid")
        if not isinstance(item.get("snapshot_available"), bool):
            issues.append(f"runs[{index}].snapshot_available_missing_or_invalid")
        if not isinstance(item.get("run_passed"), bool):
            issues.append(f"runs[{index}].run_passed_missing_or_invalid")
        if not isinstance(item.get("kpi_passed"), bool):
            issues.append(f"runs[{index}].kpi_passed_missing_or_invalid")
        failed_checks = item.get("failed_checks")
        if not _is_string_list(failed_checks):
            issues.append(f"runs[{index}].failed_checks_missing_or_invalid")
    return issues


def _validate_summary(summary: Mapping[str, object]) -> list[str]:
    issues: list[str] = []
    for key in (
        "considered_runs",
        "run_passed_count",
        "kpi_passed_count",
        "min_consensus_gap_count",
        "min_consensus_quality_count",
    ):
        value = summary.get(key)
        if value is not None and not _is_int(value):
            issues.append(f"summary.{key}_missing_or_invalid")

    for key in (
        "run_pass_rate",
        "kpi_pass_rate",
        "median_abs_consensus_gap_median",
        "median_consensus_gap_p90_abs",
    ):
        value = summary.get(key)
        if value is not None and not _is_number(value):
            issues.append(f"summary.{key}_missing_or_invalid")

    if not isinstance(summary.get("stable"), bool):
        issues.append("summary.stable_missing_or_invalid")

    stability_reasons = summary.get("stability_reasons")
    if not _is_string_list(stability_reasons):
        issues.append("summary.stability_reasons_missing_or_invalid")
    return issues


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int | float)


def _is_non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_string_list(value: object) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return False
    return all(isinstance(item, str) for item in value)


if __name__ == "__main__":
    raise SystemExit(main())
