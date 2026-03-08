from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.agents.fundamental.domain.valuation.backtest import (  # noqa: E402
    BacktestConfig,
    build_baseline_payload,
    build_report_payload,
    compare_with_baseline,
    load_baseline,
    load_cases,
    run_cases,
)
from src.agents.fundamental.domain.valuation.parameterization.forward_signal_calibration_mapping_service import (  # noqa: E402
    load_forward_signal_calibration_mapping,
)


def _default_dataset_path() -> Path:
    return PROJECT_ROOT / "tests" / "fixtures" / "fundamental_backtest_cases.json"


def _default_baseline_path() -> Path:
    return PROJECT_ROOT / "tests" / "fixtures" / "fundamental_backtest_baseline.json"


def _default_report_path() -> Path:
    return PROJECT_ROOT / "reports" / "fundamental_backtest_report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run fundamental valuation backtest against golden baseline."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=_default_dataset_path(),
        help="Path to backtest case dataset JSON.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=_default_baseline_path(),
        help="Path to baseline JSON.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=_default_report_path(),
        help="Path to output report JSON.",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Update baseline file with current run results.",
    )
    parser.add_argument(
        "--abs-tol",
        type=float,
        default=1e-6,
        help="Absolute tolerance for drift detection.",
    )
    parser.add_argument(
        "--rel-tol",
        type=float,
        default=1e-4,
        help="Relative tolerance for drift detection.",
    )
    parser.add_argument(
        "--max-extreme-upside-rate",
        type=float,
        default=0.30,
        help="Monitoring gate: maximum allowed extreme_upside_rate.",
    )
    parser.add_argument(
        "--min-guardrail-hit-rate",
        type=float,
        default=0.0,
        help="Monitoring gate: minimum allowed guardrail_hit_rate.",
    )
    parser.add_argument(
        "--min-reinvestment-guardrail-hit-rate",
        type=float,
        default=0.0,
        help="Monitoring gate: minimum allowed reinvestment_guardrail_hit_rate.",
    )
    parser.add_argument(
        "--max-shares-scope-mismatch-rate",
        type=float,
        default=1.0,
        help=(
            "Monitoring gate: maximum allowed unresolved shares_scope_mismatch_rate."
        ),
    )
    parser.add_argument(
        "--max-consensus-gap-p90-abs",
        type=float,
        default=0.60,
        help=(
            "Monitoring gate: maximum allowed consensus_gap_distribution.p90_abs "
            "when consensus coverage is available."
        ),
    )
    parser.add_argument(
        "--min-consensus-gap-count",
        type=int,
        default=2,
        help=(
            "Monitoring gate: minimum available_count required for "
            "consensus_gap_distribution before checking p90_abs."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = BacktestConfig(abs_tol=args.abs_tol, rel_tol=args.rel_tol)

    if not args.dataset.exists():
        raise FileNotFoundError(f"Backtest dataset not found: {args.dataset}")

    cases = load_cases(args.dataset)
    results = run_cases(cases)
    calibration_result = load_forward_signal_calibration_mapping()
    calibration_issue = (
        None
        if calibration_result.degraded_reason is None
        else ("calibration_mapping_degraded:" f"{calibration_result.degraded_reason}")
    )
    calibration_metadata = {
        "gate_passed": calibration_issue is None,
        "mapping_version": calibration_result.config.mapping_version,
        "mapping_source": calibration_result.mapping_source,
        "mapping_path": calibration_result.mapping_path,
        "degraded_reason": calibration_result.degraded_reason,
    }
    mapping_path_raw = calibration_result.mapping_path
    if isinstance(mapping_path_raw, str) and mapping_path_raw:
        calibration_metadata["mapping_artifact_name"] = Path(mapping_path_raw).name

    drifts = []
    baseline_issues: list[str] = []
    calibration_issues = [] if calibration_issue is None else [calibration_issue]
    monitoring_issues: list[str] = []
    issues = list(calibration_issues)
    baseline_updated = False

    if args.update_baseline:
        baseline_payload = build_baseline_payload(results)
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps(baseline_payload, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        baseline_updated = True
    else:
        if not args.baseline.exists():
            raise FileNotFoundError(
                "Baseline not found. Run with --update-baseline first: "
                f"{args.baseline}"
            )
        baseline_cases = load_baseline(args.baseline)
        drifts, baseline_issues = compare_with_baseline(
            results,
            baseline_cases,
            config=config,
        )
        issues.extend(baseline_issues)

    report_payload = build_report_payload(
        dataset_path=args.dataset,
        baseline_path=args.baseline,
        results=results,
        drifts=drifts,
        issues=issues,
        baseline_updated=baseline_updated,
        calibration=calibration_metadata,
    )
    if not baseline_updated:
        monitoring_issues = _evaluate_monitoring_gates(
            report_payload,
            max_extreme_upside_rate=args.max_extreme_upside_rate,
            min_guardrail_hit_rate=args.min_guardrail_hit_rate,
            min_reinvestment_guardrail_hit_rate=args.min_reinvestment_guardrail_hit_rate,
            max_shares_scope_mismatch_rate=args.max_shares_scope_mismatch_rate,
            max_consensus_gap_p90_abs=args.max_consensus_gap_p90_abs,
            min_consensus_gap_count=args.min_consensus_gap_count,
        )
        if monitoring_issues:
            issues.extend(monitoring_issues)
            report_payload = build_report_payload(
                dataset_path=args.dataset,
                baseline_path=args.baseline,
                results=results,
                drifts=drifts,
                issues=issues,
                baseline_updated=baseline_updated,
                calibration=calibration_metadata,
            )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    total_errors = sum(1 for item in results if item.status == "error")
    if total_errors > 0:
        print(
            f"[backtest] completed with {total_errors} case errors. report={args.report}"
        )
        return 1
    if calibration_issue is not None:
        print(
            "[backtest] calibration gate failed: "
            f"{calibration_issue} report={args.report}"
        )
        return 3
    if drifts or baseline_issues:
        print(
            "[backtest] drift/issues detected: "
            f"drifts={len(drifts)} issues={len(issues)} report={args.report}"
        )
        return 2
    if monitoring_issues:
        print(
            "[backtest] monitoring gate failed: "
            f"issues={len(monitoring_issues)} report={args.report}"
        )
        return 4
    if issues:
        print(f"[backtest] issues detected: issues={len(issues)} report={args.report}")
        return 2

    print(f"[backtest] success. report={args.report}")
    return 0


def _evaluate_monitoring_gates(
    report_payload: Mapping[str, object],
    *,
    max_extreme_upside_rate: float,
    min_guardrail_hit_rate: float,
    min_reinvestment_guardrail_hit_rate: float,
    max_shares_scope_mismatch_rate: float,
    max_consensus_gap_p90_abs: float,
    min_consensus_gap_count: int,
) -> list[str]:
    issues: list[str] = []
    summary = report_payload.get("summary")
    if not isinstance(summary, Mapping):
        return ["monitoring_gate_failed:summary_missing"]

    extreme_upside_rate = _read_number(summary, "extreme_upside_rate")
    if extreme_upside_rate is None:
        issues.append("monitoring_gate_failed:extreme_upside_rate_missing")
    elif extreme_upside_rate > max_extreme_upside_rate:
        issues.append(
            "monitoring_gate_failed:extreme_upside_rate="
            f"{extreme_upside_rate:.4f}>max:{max_extreme_upside_rate:.4f}"
        )

    guardrail_hit_rate = _read_number(summary, "guardrail_hit_rate")
    if guardrail_hit_rate is None:
        issues.append("monitoring_gate_failed:guardrail_hit_rate_missing")
    elif guardrail_hit_rate < min_guardrail_hit_rate:
        issues.append(
            "monitoring_gate_failed:guardrail_hit_rate="
            f"{guardrail_hit_rate:.4f}<min:{min_guardrail_hit_rate:.4f}"
        )

    reinvestment_guardrail_hit_rate = _read_number(
        summary, "reinvestment_guardrail_hit_rate"
    )
    if reinvestment_guardrail_hit_rate is None:
        issues.append("monitoring_gate_failed:reinvestment_guardrail_hit_rate_missing")
    elif reinvestment_guardrail_hit_rate < min_reinvestment_guardrail_hit_rate:
        issues.append(
            "monitoring_gate_failed:reinvestment_guardrail_hit_rate="
            f"{reinvestment_guardrail_hit_rate:.4f}"
            f"<min:{min_reinvestment_guardrail_hit_rate:.4f}"
        )

    shares_scope_mismatch_rate = _read_number(summary, "shares_scope_mismatch_rate")
    if shares_scope_mismatch_rate is None:
        issues.append("monitoring_gate_failed:shares_scope_mismatch_rate_missing")
    elif shares_scope_mismatch_rate > max_shares_scope_mismatch_rate:
        issues.append(
            "monitoring_gate_failed:shares_scope_mismatch_rate="
            f"{shares_scope_mismatch_rate:.4f}>max:{max_shares_scope_mismatch_rate:.4f}"
        )

    consensus_distribution = summary.get("consensus_gap_distribution")
    if not isinstance(consensus_distribution, Mapping):
        issues.append("monitoring_gate_failed:consensus_gap_distribution_missing")
        return issues

    available_count_raw = consensus_distribution.get("available_count")
    if not isinstance(available_count_raw, int):
        issues.append("monitoring_gate_failed:consensus_gap_available_count_missing")
        return issues
    if available_count_raw < min_consensus_gap_count:
        issues.append(
            "monitoring_gate_failed:consensus_gap_available_count="
            f"{available_count_raw}<min:{min_consensus_gap_count}"
        )
        return issues

    if available_count_raw > 0:
        consensus_gap_p90_abs = _read_number(consensus_distribution, "p90_abs")
        if consensus_gap_p90_abs is None:
            issues.append("monitoring_gate_failed:consensus_gap_p90_abs_missing")
        elif consensus_gap_p90_abs > max_consensus_gap_p90_abs:
            issues.append(
                "monitoring_gate_failed:consensus_gap_p90_abs="
                f"{consensus_gap_p90_abs:.4f}>max:{max_consensus_gap_p90_abs:.4f}"
            )

    return issues


def _read_number(payload: Mapping[str, object], key: str) -> float | None:
    value = payload.get(key)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
