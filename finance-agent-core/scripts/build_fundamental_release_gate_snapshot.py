from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build machine-readable snapshot for fundamental release gate."
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path to fundamental backtest report JSON.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write release gate snapshot JSON.",
    )
    parser.add_argument(
        "--exit-code",
        type=int,
        required=True,
        help="Release gate shell exit code.",
    )
    parser.add_argument(
        "--gate-profile",
        type=str,
        default="unknown",
        help="Gate profile identifier.",
    )
    parser.add_argument(
        "--gate-error-codes",
        type=str,
        default="",
        help="Comma-separated gate error codes.",
    )
    parser.add_argument(
        "--replay-report",
        type=Path,
        default=None,
        help="Path to replay checks report JSON.",
    )
    parser.add_argument(
        "--live-replay-run-report",
        type=Path,
        default=None,
        help="Path to live replay cohort run JSON.",
    )
    parser.add_argument(
        "--reinvestment-clamp-profile-report",
        type=Path,
        default=None,
        help="Path to reinvestment clamp profile validation JSON.",
    )
    parser.add_argument("--max-consensus-gap-median-abs", type=float, default=None)
    parser.add_argument("--max-consensus-gap-p90-abs", type=float, default=None)
    parser.add_argument("--min-consensus-gap-count", type=int, default=None)
    parser.add_argument("--max-consensus-degraded-rate", type=float, default=None)
    parser.add_argument("--min-consensus-confidence-weight", type=float, default=None)
    parser.add_argument("--min-consensus-quality-count", type=int, default=None)
    parser.add_argument(
        "--max-consensus-provider-blocked-rate",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--max-consensus-parse-missing-rate",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--min-consensus-warning-code-count",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--min-replay-trace-contract-pass-rate", type=float, default=None
    )
    parser.add_argument(
        "--max-replay-intrinsic-delta-p90-abs",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--max-replay-quality-block-rate",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--min-replay-cache-hit-rate",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--max-replay-warm-latency-p90-ms",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--max-replay-cold-latency-p90-ms",
        type=float,
        default=None,
    )
    parser.add_argument(
        "--max-replay-validation-rule-drift-count",
        type=int,
        default=None,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    report_payload = _read_report_payload(args.report)
    replay_payload = _read_report_payload(args.replay_report)
    live_replay_payload = _read_report_payload(args.live_replay_run_report)
    reinvestment_profile_payload = _read_report_payload(
        args.reinvestment_clamp_profile_report
    )
    summary = _extract_summary(report_payload)
    replay_summary = _extract_replay_summary(replay_payload)
    live_replay_summary = _extract_live_replay_summary(live_replay_payload)
    reinvestment_profile_summary = _extract_reinvestment_profile_summary(
        reinvestment_profile_payload
    )
    if replay_summary:
        summary["replay_checks"] = replay_summary
    if live_replay_summary:
        summary["live_replay"] = live_replay_summary
    if reinvestment_profile_summary:
        summary["reinvestment_clamp_profile"] = reinvestment_profile_summary
    issues = _extract_issues(report_payload)

    snapshot = {
        "generated_at": _utc_now_iso(),
        "gate_profile": args.gate_profile,
        "release_gate_exit_code": args.exit_code,
        "gate_error_codes": _parse_error_codes(args.gate_error_codes),
        "report_path": str(args.report),
        "report_available": report_payload is not None,
        "replay_report_path": str(args.replay_report) if args.replay_report else None,
        "replay_report_available": replay_payload is not None
        if args.replay_report
        else False,
        "live_replay_run_path": (
            str(args.live_replay_run_report) if args.live_replay_run_report else None
        ),
        "live_replay_run_available": (
            live_replay_payload is not None if args.live_replay_run_report else False
        ),
        "reinvestment_clamp_profile_report_path": (
            str(args.reinvestment_clamp_profile_report)
            if args.reinvestment_clamp_profile_report
            else None
        ),
        "reinvestment_clamp_profile_report_available": (
            reinvestment_profile_payload is not None
            if args.reinvestment_clamp_profile_report
            else False
        ),
        "thresholds": _build_thresholds(args),
        "summary": summary,
        "issues": issues,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _read_report_payload(path: Path | None) -> Mapping[str, object] | None:
    if path is None:
        return None
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(raw, Mapping):
        return raw
    return None


def _extract_summary(report_payload: Mapping[str, object] | None) -> dict[str, object]:
    if not isinstance(report_payload, Mapping):
        return {}
    summary_raw = report_payload.get("summary")
    if not isinstance(summary_raw, Mapping):
        return {}

    output: dict[str, object] = {}
    _copy_numeric(summary_raw, output, "total_cases")
    _copy_numeric(summary_raw, output, "ok")
    _copy_numeric(summary_raw, output, "errors")
    _copy_numeric(summary_raw, output, "issue_count")
    _copy_numeric(summary_raw, output, "consensus_degraded_rate")
    _copy_numeric(summary_raw, output, "consensus_confidence_weight_avg")
    _copy_numeric(summary_raw, output, "shares_scope_mismatch_rate")
    _copy_numeric(summary_raw, output, "guardrail_hit_rate")
    _copy_numeric(summary_raw, output, "consensus_provider_blocked_rate")
    _copy_numeric(summary_raw, output, "consensus_parse_missing_rate")

    gap_distribution = summary_raw.get("consensus_gap_distribution")
    if isinstance(gap_distribution, Mapping):
        normalized_gap: dict[str, object] = {}
        _copy_numeric(gap_distribution, normalized_gap, "available_count")
        _copy_numeric(gap_distribution, normalized_gap, "median")
        _copy_numeric(gap_distribution, normalized_gap, "p90_abs")
        if normalized_gap:
            output["consensus_gap_distribution"] = normalized_gap

    warning_code_distribution = summary_raw.get("consensus_warning_code_distribution")
    if isinstance(warning_code_distribution, Mapping):
        normalized_warning_distribution: dict[str, object] = {}
        _copy_numeric(
            warning_code_distribution,
            normalized_warning_distribution,
            "available_count",
        )
        code_case_counts_raw = warning_code_distribution.get("code_case_counts")
        if isinstance(code_case_counts_raw, Mapping):
            normalized_counts: dict[str, int] = {}
            for key, value in code_case_counts_raw.items():
                if (
                    isinstance(key, str)
                    and isinstance(value, int)
                    and not isinstance(value, bool)
                ):
                    normalized_counts[key] = value
            normalized_warning_distribution["code_case_counts"] = normalized_counts
        code_case_rates_raw = warning_code_distribution.get("code_case_rates")
        if isinstance(code_case_rates_raw, Mapping):
            normalized_rates: dict[str, float] = {}
            for key, value in code_case_rates_raw.items():
                if isinstance(key, str) and isinstance(value, int | float):
                    if not isinstance(value, bool):
                        normalized_rates[key] = float(value)
            normalized_warning_distribution["code_case_rates"] = normalized_rates
        if normalized_warning_distribution:
            output["consensus_warning_code_distribution"] = (
                normalized_warning_distribution
            )

    return output


def _extract_issues(report_payload: Mapping[str, object] | None) -> list[str]:
    if not isinstance(report_payload, Mapping):
        return []
    issues_raw = report_payload.get("issues")
    if not isinstance(issues_raw, Sequence):
        return []
    return [item for item in issues_raw if isinstance(item, str) and item]


def _extract_replay_summary(
    report_payload: Mapping[str, object] | None,
) -> dict[str, object]:
    if not isinstance(report_payload, Mapping):
        return {}
    summary_raw = report_payload.get("summary")
    if not isinstance(summary_raw, Mapping):
        return {}

    output: dict[str, object] = {}
    _copy_numeric(summary_raw, output, "total_cases")
    _copy_numeric(summary_raw, output, "passed_cases")
    _copy_numeric(summary_raw, output, "failed_cases")
    _copy_numeric(summary_raw, output, "trace_contract_pass_rate")
    _copy_numeric(summary_raw, output, "intrinsic_delta_available_cases")
    _copy_numeric(summary_raw, output, "intrinsic_delta_p90_abs")
    _copy_numeric(summary_raw, output, "quality_block_rate")
    _copy_numeric(summary_raw, output, "validation_block_rate")
    _copy_numeric(summary_raw, output, "cache_hit_rate")
    _copy_numeric_or_none(summary_raw, output, "warm_latency_p90_ms")
    _copy_numeric_or_none(summary_raw, output, "cold_latency_p90_ms")
    _copy_numeric(summary_raw, output, "validation_rule_drift_count")
    _copy_bool(summary_raw, output, "validation_rule_drift_detected")
    _copy_text(summary_raw, output, "validation_rule_actual_signature")
    _copy_text(summary_raw, output, "validation_rule_expected_signature")
    _copy_text(summary_raw, output, "validation_rule_drift_error_code")
    validation_rule_runtime_raw = summary_raw.get("validation_rule_runtime")
    if isinstance(validation_rule_runtime_raw, Mapping):
        output["validation_rule_runtime"] = dict(validation_rule_runtime_raw)
    error_code_counts_raw = summary_raw.get("error_code_counts")
    if isinstance(error_code_counts_raw, Mapping):
        normalized_counts: dict[str, int] = {}
        for key, value in error_code_counts_raw.items():
            if not isinstance(key, str):
                continue
            if isinstance(value, int) and not isinstance(value, bool):
                normalized_counts[key] = value
        output["error_code_counts"] = normalized_counts
    return output


def _extract_live_replay_summary(
    report_payload: Mapping[str, object] | None,
) -> dict[str, object]:
    if not isinstance(report_payload, Mapping):
        return {}
    output: dict[str, object] = {}
    gate_passed = report_payload.get("gate_passed")
    if isinstance(gate_passed, bool):
        output["gate_passed"] = gate_passed
    issues_raw = report_payload.get("issues")
    if isinstance(issues_raw, Sequence):
        output["issues"] = [item for item in issues_raw if isinstance(item, str)]
    profile = report_payload.get("profile")
    if isinstance(profile, str) and profile.strip():
        output["profile"] = profile.strip()
    cycle_tag = report_payload.get("cycle_tag")
    if isinstance(cycle_tag, str) and cycle_tag.strip():
        output["cycle_tag"] = cycle_tag.strip()
    return output


def _extract_reinvestment_profile_summary(
    report_payload: Mapping[str, object] | None,
) -> dict[str, object]:
    if not isinstance(report_payload, Mapping):
        return {}
    output: dict[str, object] = {}
    gate_passed = report_payload.get("gate_passed")
    if isinstance(gate_passed, bool):
        output["gate_passed"] = gate_passed
    profile_version = report_payload.get("profile_version")
    if isinstance(profile_version, str) and profile_version.strip():
        output["profile_version"] = profile_version.strip()
    as_of_date = report_payload.get("as_of_date")
    if isinstance(as_of_date, str) and as_of_date.strip():
        output["as_of_date"] = as_of_date.strip()
    _copy_numeric(report_payload, output, "age_days")
    _copy_numeric(report_payload, output, "evidence_ref_count")
    issues_raw = report_payload.get("issues")
    if isinstance(issues_raw, Sequence):
        output["issues"] = [item for item in issues_raw if isinstance(item, str)]
    return output


def _copy_numeric(
    source: Mapping[str, object],
    target: dict[str, object],
    key: str,
) -> None:
    value = source.get(key)
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        target[key] = value
    elif isinstance(value, float):
        target[key] = float(value)


def _copy_numeric_or_none(
    source: Mapping[str, object],
    target: dict[str, object],
    key: str,
) -> None:
    if key not in source:
        return
    value = source.get(key)
    if value is None:
        target[key] = None
        return
    if isinstance(value, bool):
        return
    if isinstance(value, int):
        target[key] = value
        return
    if isinstance(value, float):
        target[key] = float(value)


def _copy_bool(
    source: Mapping[str, object],
    target: dict[str, object],
    key: str,
) -> None:
    value = source.get(key)
    if isinstance(value, bool):
        target[key] = value


def _copy_text(
    source: Mapping[str, object],
    target: dict[str, object],
    key: str,
) -> None:
    value = source.get(key)
    if isinstance(value, str) and value.strip():
        target[key] = value.strip()


def _parse_error_codes(raw: str) -> list[str]:
    if not raw.strip():
        return []
    return [item for item in (part.strip() for part in raw.split(",")) if item]


def _build_thresholds(args: argparse.Namespace) -> dict[str, object]:
    thresholds: dict[str, object] = {}
    for key in (
        "max_consensus_gap_median_abs",
        "max_consensus_gap_p90_abs",
        "min_consensus_gap_count",
        "max_consensus_degraded_rate",
        "min_consensus_confidence_weight",
        "min_consensus_quality_count",
        "max_consensus_provider_blocked_rate",
        "max_consensus_parse_missing_rate",
        "min_consensus_warning_code_count",
        "min_replay_trace_contract_pass_rate",
        "max_replay_intrinsic_delta_p90_abs",
        "max_replay_quality_block_rate",
        "min_replay_cache_hit_rate",
        "max_replay_warm_latency_p90_ms",
        "max_replay_cold_latency_p90_ms",
        "max_replay_validation_rule_drift_count",
    ):
        value = getattr(args, key)
        if value is None:
            continue
        thresholds[key] = value
    return thresholds


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
