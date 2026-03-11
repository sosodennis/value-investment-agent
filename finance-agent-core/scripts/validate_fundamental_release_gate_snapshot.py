from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate fundamental release gate snapshot artifact.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        required=True,
        help="Release gate snapshot JSON path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = _read_payload(args.path)
    issues = _validate_payload(payload)

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
        raise TypeError("snapshot root must be an object")
    return parsed


def _validate_payload(payload: Mapping[str, object]) -> list[str]:
    issues: list[str] = []

    if not _is_non_empty_text(payload.get("generated_at")):
        issues.append("generated_at_missing_or_invalid")
    if not _is_non_empty_text(payload.get("gate_profile")):
        issues.append("gate_profile_missing_or_invalid")
    if not _is_int(payload.get("release_gate_exit_code")):
        issues.append("release_gate_exit_code_missing_or_invalid")
    if not _is_non_empty_text(payload.get("report_path")):
        issues.append("report_path_missing_or_invalid")
    if not isinstance(payload.get("report_available"), bool):
        issues.append("report_available_missing_or_invalid")
    replay_report_path = payload.get("replay_report_path")
    if replay_report_path is not None and not _is_non_empty_text(replay_report_path):
        issues.append("replay_report_path_missing_or_invalid")
    replay_report_available = payload.get("replay_report_available")
    if replay_report_path is not None and not isinstance(replay_report_available, bool):
        issues.append("replay_report_available_missing_or_invalid")
    live_replay_run_path = payload.get("live_replay_run_path")
    if live_replay_run_path is not None and not _is_non_empty_text(
        live_replay_run_path
    ):
        issues.append("live_replay_run_path_missing_or_invalid")
    live_replay_run_available = payload.get("live_replay_run_available")
    if live_replay_run_path is not None and not isinstance(
        live_replay_run_available, bool
    ):
        issues.append("live_replay_run_available_missing_or_invalid")
    reinvestment_profile_report_path = payload.get(
        "reinvestment_clamp_profile_report_path"
    )
    if reinvestment_profile_report_path is not None and not _is_non_empty_text(
        reinvestment_profile_report_path
    ):
        issues.append("reinvestment_clamp_profile_report_path_missing_or_invalid")
    reinvestment_profile_report_available = payload.get(
        "reinvestment_clamp_profile_report_available"
    )
    if reinvestment_profile_report_path is not None and not isinstance(
        reinvestment_profile_report_available, bool
    ):
        issues.append("reinvestment_clamp_profile_report_available_missing_or_invalid")

    gate_error_codes = payload.get("gate_error_codes")
    if not _is_string_list(gate_error_codes):
        issues.append("gate_error_codes_missing_or_invalid")

    thresholds = payload.get("thresholds")
    if not isinstance(thresholds, Mapping):
        issues.append("thresholds_missing_or_invalid")

    summary_raw = payload.get("summary")
    if not isinstance(summary_raw, Mapping):
        issues.append("summary_missing_or_invalid")
    else:
        issues.extend(_validate_summary(summary_raw))
        if isinstance(replay_report_path, str) and replay_report_path:
            issues.extend(
                _validate_replay_checks_summary(
                    summary=summary_raw,
                    replay_report_available=bool(replay_report_available),
                )
            )
        if isinstance(live_replay_run_path, str) and live_replay_run_path:
            issues.extend(
                _validate_live_replay_summary(
                    summary=summary_raw,
                    live_replay_run_available=bool(live_replay_run_available),
                )
            )
        if (
            isinstance(reinvestment_profile_report_path, str)
            and reinvestment_profile_report_path
        ):
            issues.extend(
                _validate_reinvestment_profile_summary(
                    summary=summary_raw,
                    reinvestment_profile_report_available=bool(
                        reinvestment_profile_report_available
                    ),
                )
            )

    issues_raw = payload.get("issues")
    if not _is_string_list(issues_raw):
        issues.append("issues_missing_or_invalid")

    return issues


def _validate_summary(summary: Mapping[str, object]) -> list[str]:
    issues: list[str] = []
    for key in (
        "total_cases",
        "ok",
        "errors",
        "issue_count",
        "consensus_degraded_rate",
        "consensus_confidence_weight_avg",
        "shares_scope_mismatch_rate",
        "guardrail_hit_rate",
        "consensus_provider_blocked_rate",
        "consensus_parse_missing_rate",
    ):
        if not _is_number(summary.get(key)):
            issues.append(f"summary.{key}_missing_or_invalid")

    gap_raw = summary.get("consensus_gap_distribution")
    if not isinstance(gap_raw, Mapping):
        issues.append("summary.consensus_gap_distribution_missing_or_invalid")
        return issues

    available_count = gap_raw.get("available_count")
    if not _is_number(available_count):
        issues.append(
            "summary.consensus_gap_distribution.available_count_missing_or_invalid"
        )
        return issues

    if isinstance(available_count, int | float) and float(available_count) > 0:
        if not _is_number(gap_raw.get("median")):
            issues.append(
                "summary.consensus_gap_distribution.median_missing_or_invalid"
            )
        if not _is_number(gap_raw.get("p90_abs")):
            issues.append(
                "summary.consensus_gap_distribution.p90_abs_missing_or_invalid"
            )

    warning_code_distribution_raw = summary.get("consensus_warning_code_distribution")
    if not isinstance(warning_code_distribution_raw, Mapping):
        issues.append("summary.consensus_warning_code_distribution_missing_or_invalid")
        return issues

    warning_available_count = warning_code_distribution_raw.get("available_count")
    if not _is_number(warning_available_count):
        issues.append(
            "summary.consensus_warning_code_distribution.available_count_missing_or_invalid"
        )
        return issues

    if (
        isinstance(warning_available_count, int | float)
        and float(warning_available_count) > 0
    ):
        code_case_counts = warning_code_distribution_raw.get("code_case_counts")
        if not _is_string_numeric_mapping(code_case_counts, allow_float=False):
            issues.append(
                "summary.consensus_warning_code_distribution.code_case_counts_missing_or_invalid"
            )
        code_case_rates = warning_code_distribution_raw.get("code_case_rates")
        if not _is_string_numeric_mapping(code_case_rates, allow_float=True):
            issues.append(
                "summary.consensus_warning_code_distribution.code_case_rates_missing_or_invalid"
            )
    return issues


def _validate_replay_checks_summary(
    *,
    summary: Mapping[str, object],
    replay_report_available: bool,
) -> list[str]:
    issues: list[str] = []
    replay_checks_raw = summary.get("replay_checks")
    if not replay_report_available:
        if replay_checks_raw is not None and not isinstance(replay_checks_raw, Mapping):
            issues.append("summary.replay_checks_missing_or_invalid")
        return issues

    if not isinstance(replay_checks_raw, Mapping):
        issues.append("summary.replay_checks_missing_or_invalid")
        return issues

    for key in (
        "total_cases",
        "passed_cases",
        "failed_cases",
        "trace_contract_pass_rate",
    ):
        if not _is_number(replay_checks_raw.get(key)):
            issues.append(f"summary.replay_checks.{key}_missing_or_invalid")
    for key in (
        "quality_block_rate",
        "validation_block_rate",
        "cache_hit_rate",
    ):
        if not _is_number(replay_checks_raw.get(key)):
            issues.append(f"summary.replay_checks.{key}_missing_or_invalid")
    for key in ("warm_latency_p90_ms", "cold_latency_p90_ms"):
        if key not in replay_checks_raw:
            issues.append(f"summary.replay_checks.{key}_missing_or_invalid")
            continue
        value = replay_checks_raw.get(key)
        if value is not None and not _is_number(value):
            issues.append(f"summary.replay_checks.{key}_missing_or_invalid")
    error_code_counts = replay_checks_raw.get("error_code_counts")
    if error_code_counts is not None and not isinstance(error_code_counts, Mapping):
        issues.append("summary.replay_checks.error_code_counts_missing_or_invalid")
    validation_rule_drift_count = replay_checks_raw.get("validation_rule_drift_count")
    if validation_rule_drift_count is not None and not _is_number(
        validation_rule_drift_count
    ):
        issues.append(
            "summary.replay_checks.validation_rule_drift_count_missing_or_invalid"
        )
    validation_rule_drift_detected = replay_checks_raw.get(
        "validation_rule_drift_detected"
    )
    if validation_rule_drift_detected is not None and not isinstance(
        validation_rule_drift_detected, bool
    ):
        issues.append(
            "summary.replay_checks.validation_rule_drift_detected_missing_or_invalid"
        )
    for key in (
        "validation_rule_actual_signature",
        "validation_rule_expected_signature",
        "validation_rule_drift_error_code",
    ):
        value = replay_checks_raw.get(key)
        if value is not None and not _is_non_empty_text(value):
            issues.append(f"summary.replay_checks.{key}_missing_or_invalid")
    validation_rule_runtime = replay_checks_raw.get("validation_rule_runtime")
    if validation_rule_runtime is not None and not isinstance(
        validation_rule_runtime, Mapping
    ):
        issues.append(
            "summary.replay_checks.validation_rule_runtime_missing_or_invalid"
        )
    return issues


def _validate_live_replay_summary(
    *,
    summary: Mapping[str, object],
    live_replay_run_available: bool,
) -> list[str]:
    issues: list[str] = []
    live_replay_raw = summary.get("live_replay")
    if not live_replay_run_available:
        if live_replay_raw is not None and not isinstance(live_replay_raw, Mapping):
            issues.append("summary.live_replay_missing_or_invalid")
        return issues

    if not isinstance(live_replay_raw, Mapping):
        issues.append("summary.live_replay_missing_or_invalid")
        return issues

    gate_passed = live_replay_raw.get("gate_passed")
    if not isinstance(gate_passed, bool):
        issues.append("summary.live_replay.gate_passed_missing_or_invalid")
    issues_raw = live_replay_raw.get("issues")
    if issues_raw is not None and not _is_string_list(issues_raw):
        issues.append("summary.live_replay.issues_missing_or_invalid")
    return issues


def _validate_reinvestment_profile_summary(
    *,
    summary: Mapping[str, object],
    reinvestment_profile_report_available: bool,
) -> list[str]:
    issues: list[str] = []
    reinvestment_profile_raw = summary.get("reinvestment_clamp_profile")
    if not reinvestment_profile_report_available:
        if reinvestment_profile_raw is not None and not isinstance(
            reinvestment_profile_raw, Mapping
        ):
            issues.append("summary.reinvestment_clamp_profile_missing_or_invalid")
        return issues

    if not isinstance(reinvestment_profile_raw, Mapping):
        issues.append("summary.reinvestment_clamp_profile_missing_or_invalid")
        return issues

    gate_passed = reinvestment_profile_raw.get("gate_passed")
    if not isinstance(gate_passed, bool):
        issues.append(
            "summary.reinvestment_clamp_profile.gate_passed_missing_or_invalid"
        )
    if not _is_non_empty_text(reinvestment_profile_raw.get("profile_version")):
        issues.append(
            "summary.reinvestment_clamp_profile.profile_version_missing_or_invalid"
        )
    if not _is_non_empty_text(reinvestment_profile_raw.get("as_of_date")):
        issues.append(
            "summary.reinvestment_clamp_profile.as_of_date_missing_or_invalid"
        )
    for key in ("age_days", "evidence_ref_count"):
        if not _is_number(reinvestment_profile_raw.get(key)):
            issues.append(
                f"summary.reinvestment_clamp_profile.{key}_missing_or_invalid"
            )
    issues_raw = reinvestment_profile_raw.get("issues")
    if issues_raw is not None and not _is_string_list(issues_raw):
        issues.append("summary.reinvestment_clamp_profile.issues_missing_or_invalid")
    return issues


def _is_number(value: object) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int | float)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_non_empty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_string_list(value: object) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return False
    return all(isinstance(item, str) for item in value)


def _is_string_numeric_mapping(value: object, *, allow_float: bool) -> bool:
    if not isinstance(value, Mapping):
        return False
    for key, raw in value.items():
        if not _is_non_empty_text(key):
            return False
        if allow_float:
            if not _is_number(raw):
                return False
            continue
        if not _is_int(raw):
            return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
