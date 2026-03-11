from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.agents.fundamental.core_valuation.interface.replay_contracts import (  # noqa: E402
    ValuationReplayInputModel,
    ValuationReplayManifestModel,
    parse_valuation_replay_input_model,
    parse_valuation_replay_manifest_model,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate live replay cohort coverage and pass-rate gate."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Path to valuation_replay_manifest_v1 JSON.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path to fundamental_replay_checks_report_v1 JSON.",
    )
    parser.add_argument(
        "--min-cases",
        type=int,
        default=4,
        help="Minimum required replay cohort case count.",
    )
    parser.add_argument(
        "--min-unique-tickers",
        type=int,
        default=4,
        help="Minimum required unique ticker count in replay cohort.",
    )
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=1.0,
        help="Minimum required replay trace-contract pass rate (0~1).",
    )
    parser.add_argument(
        "--max-intrinsic-delta-p90-abs",
        type=float,
        default=None,
        help=(
            "Optional maximum allowed p90 absolute intrinsic delta "
            "from replay checks report summary."
        ),
    )
    parser.add_argument(
        "--max-quality-block-rate",
        type=float,
        default=None,
        help=(
            "Optional maximum allowed quality_block_rate "
            "from replay checks report summary."
        ),
    )
    parser.add_argument(
        "--min-cache-hit-rate",
        type=float,
        default=None,
        help=(
            "Optional minimum allowed cache_hit_rate "
            "from replay checks report summary."
        ),
    )
    parser.add_argument(
        "--max-warm-latency-p90-ms",
        type=float,
        default=None,
        help=(
            "Optional maximum allowed warm_latency_p90_ms "
            "from replay checks report summary."
        ),
    )
    parser.add_argument(
        "--max-cold-latency-p90-ms",
        type=float,
        default=None,
        help=(
            "Optional maximum allowed cold_latency_p90_ms "
            "from replay checks report summary."
        ),
    )
    parser.add_argument(
        "--max-arelle-parse-latency-p90-ms",
        type=float,
        default=None,
        help=(
            "Optional maximum allowed arelle_parse_latency_p90_ms "
            "from replay checks report summary."
        ),
    )
    parser.add_argument(
        "--max-arelle-runtime-lock-wait-p90-ms",
        type=float,
        default=None,
        help=(
            "Optional maximum allowed arelle_runtime_lock_wait_p90_ms "
            "from replay checks report summary."
        ),
    )
    parser.add_argument(
        "--max-validation-rule-drift-count",
        type=int,
        default=None,
        help=(
            "Optional maximum allowed validation_rule_drift_count "
            "from replay checks report summary."
        ),
    )
    parser.add_argument(
        "--require-relative-input-paths",
        action="store_true",
        help="Require manifest case input_path values to be relative paths.",
    )
    parser.add_argument(
        "--require-input-root",
        type=Path,
        default=None,
        help=("Optional root directory; resolved input paths must be under this root."),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = _load_manifest(args.manifest)
    report = _load_report(args.report)
    evaluation = _evaluate(
        manifest=manifest,
        report=report,
        manifest_path=args.manifest,
        min_cases=int(args.min_cases),
        min_unique_tickers=int(args.min_unique_tickers),
        min_pass_rate=float(args.min_pass_rate),
        max_intrinsic_delta_p90_abs=(
            float(args.max_intrinsic_delta_p90_abs)
            if args.max_intrinsic_delta_p90_abs is not None
            else None
        ),
        max_quality_block_rate=(
            float(args.max_quality_block_rate)
            if args.max_quality_block_rate is not None
            else None
        ),
        min_cache_hit_rate=(
            float(args.min_cache_hit_rate)
            if args.min_cache_hit_rate is not None
            else None
        ),
        max_warm_latency_p90_ms=(
            float(args.max_warm_latency_p90_ms)
            if args.max_warm_latency_p90_ms is not None
            else None
        ),
        max_cold_latency_p90_ms=(
            float(args.max_cold_latency_p90_ms)
            if args.max_cold_latency_p90_ms is not None
            else None
        ),
        max_arelle_parse_latency_p90_ms=(
            float(args.max_arelle_parse_latency_p90_ms)
            if args.max_arelle_parse_latency_p90_ms is not None
            else None
        ),
        max_arelle_runtime_lock_wait_p90_ms=(
            float(args.max_arelle_runtime_lock_wait_p90_ms)
            if args.max_arelle_runtime_lock_wait_p90_ms is not None
            else None
        ),
        max_validation_rule_drift_count=(
            int(args.max_validation_rule_drift_count)
            if args.max_validation_rule_drift_count is not None
            else None
        ),
        require_relative_input_paths=bool(args.require_relative_input_paths),
        require_input_root=(
            args.require_input_root.resolve()
            if args.require_input_root is not None
            else None
        ),
    )
    print(json.dumps(evaluation, ensure_ascii=False))
    if bool(evaluation.get("gate_passed")):
        return 0
    return 1


def _load_manifest(path: Path) -> ValuationReplayManifestModel:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return parse_valuation_replay_manifest_model(raw, context=f"cohort.manifest:{path}")


def _load_report(path: Path) -> Mapping[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, Mapping):
        raise TypeError("replay checks report root must be an object")
    return parsed


def _evaluate(
    *,
    manifest: ValuationReplayManifestModel,
    report: Mapping[str, object],
    manifest_path: Path,
    min_cases: int,
    min_unique_tickers: int,
    min_pass_rate: float,
    max_intrinsic_delta_p90_abs: float | None,
    max_quality_block_rate: float | None,
    min_cache_hit_rate: float | None,
    max_warm_latency_p90_ms: float | None,
    max_cold_latency_p90_ms: float | None,
    max_arelle_parse_latency_p90_ms: float | None,
    max_arelle_runtime_lock_wait_p90_ms: float | None,
    max_validation_rule_drift_count: int | None,
    require_relative_input_paths: bool,
    require_input_root: Path | None,
) -> dict[str, object]:
    issues: list[str] = []
    manifest_cases = len(manifest.cases)
    if manifest_cases < min_cases:
        issues.append("manifest_case_count_below_min")

    tickers = _extract_unique_tickers(manifest=manifest, manifest_path=manifest_path)
    unique_tickers = len(tickers)
    if unique_tickers < min_unique_tickers:
        issues.append("manifest_unique_ticker_count_below_min")

    invalid_relative_count = 0
    outside_root_count = 0
    for case in manifest.cases:
        input_ref = Path(case.input_path)
        if require_relative_input_paths and input_ref.is_absolute():
            invalid_relative_count += 1
        if require_input_root is not None:
            resolved = _resolve_input_path(
                manifest_path=manifest_path,
                input_path=case.input_path,
            )
            if not _is_under_root(resolved, require_input_root):
                outside_root_count += 1
    if invalid_relative_count > 0:
        issues.append("manifest_input_path_absolute_disallowed")
    if outside_root_count > 0:
        issues.append("manifest_input_path_outside_required_root")

    summary_raw = report.get("summary")
    if not isinstance(summary_raw, Mapping):
        issues.append("replay_report_summary_missing_or_invalid")
        replay_total_cases = None
        replay_pass_rate = None
        replay_failed_cases = None
    else:
        replay_total_cases = _coerce_int(summary_raw.get("total_cases"))
        replay_passed_cases = _coerce_int(summary_raw.get("passed_cases"))
        replay_failed_cases = _coerce_int(summary_raw.get("failed_cases"))
        replay_pass_rate = _coerce_float(summary_raw.get("trace_contract_pass_rate"))
        if replay_total_cases is None:
            issues.append("replay_report_total_cases_missing_or_invalid")
        elif replay_total_cases < min_cases:
            issues.append("replay_report_case_count_below_min")
        if replay_failed_cases is None:
            issues.append("replay_report_failed_cases_missing_or_invalid")
        elif replay_failed_cases > 0:
            issues.append("replay_report_failed_cases_nonzero")
        if replay_pass_rate is None:
            if replay_total_cases and replay_passed_cases is not None:
                replay_pass_rate = replay_passed_cases / replay_total_cases
            else:
                issues.append("replay_report_pass_rate_missing_or_invalid")
        if replay_pass_rate is not None and replay_pass_rate < min_pass_rate:
            issues.append("replay_report_pass_rate_below_min")

    replay_intrinsic_delta_available_cases = None
    replay_intrinsic_delta_p90_abs = None
    replay_quality_block_rate = None
    replay_validation_block_rate = None
    replay_cache_hit_rate = None
    replay_warm_latency_p90_ms = None
    replay_cold_latency_p90_ms = None
    replay_arelle_parse_latency_p90_ms = None
    replay_arelle_runtime_lock_wait_p90_ms = None
    replay_validation_rule_drift_count = None
    if isinstance(summary_raw, Mapping):
        replay_intrinsic_delta_available_cases = _coerce_int(
            summary_raw.get("intrinsic_delta_available_cases")
        )
        replay_intrinsic_delta_p90_abs = _coerce_float(
            summary_raw.get("intrinsic_delta_p90_abs")
        )
        if max_intrinsic_delta_p90_abs is not None:
            if replay_intrinsic_delta_available_cases is None:
                issues.append(
                    "replay_report_intrinsic_delta_available_cases_missing_or_invalid"
                )
            elif replay_intrinsic_delta_available_cases <= 0:
                issues.append("replay_report_intrinsic_delta_available_cases_empty")
            if replay_intrinsic_delta_p90_abs is None:
                issues.append(
                    "replay_report_intrinsic_delta_p90_abs_missing_or_invalid"
                )
            elif replay_intrinsic_delta_p90_abs > max_intrinsic_delta_p90_abs:
                issues.append("replay_report_intrinsic_delta_p90_abs_above_max")
    elif max_intrinsic_delta_p90_abs is not None:
        issues.append("replay_report_intrinsic_delta_distribution_missing_or_invalid")

    if isinstance(summary_raw, Mapping):
        replay_quality_block_rate = _coerce_float(summary_raw.get("quality_block_rate"))
        replay_validation_block_rate = _coerce_float(
            summary_raw.get("validation_block_rate")
        )
        if replay_validation_block_rate is None:
            replay_validation_block_rate = replay_quality_block_rate
        if max_quality_block_rate is not None:
            if replay_validation_block_rate is None:
                issues.append("replay_report_quality_block_rate_missing_or_invalid")
            elif replay_validation_block_rate > max_quality_block_rate:
                issues.append("replay_report_quality_block_rate_above_max")

        replay_cache_hit_rate = _coerce_float(summary_raw.get("cache_hit_rate"))
        if min_cache_hit_rate is not None:
            if replay_cache_hit_rate is None:
                issues.append("replay_report_cache_hit_rate_missing_or_invalid")
            elif replay_cache_hit_rate < min_cache_hit_rate:
                issues.append("replay_report_cache_hit_rate_below_min")

        replay_warm_latency_p90_ms = _coerce_float(
            summary_raw.get("warm_latency_p90_ms")
        )
        if max_warm_latency_p90_ms is not None:
            if replay_warm_latency_p90_ms is not None and (
                replay_warm_latency_p90_ms > max_warm_latency_p90_ms
            ):
                issues.append("replay_report_warm_latency_p90_ms_above_max")

        replay_cold_latency_p90_ms = _coerce_float(
            summary_raw.get("cold_latency_p90_ms")
        )
        if max_cold_latency_p90_ms is not None:
            if replay_cold_latency_p90_ms is None:
                issues.append("replay_report_cold_latency_p90_ms_missing_or_invalid")
            elif replay_cold_latency_p90_ms > max_cold_latency_p90_ms:
                issues.append("replay_report_cold_latency_p90_ms_above_max")

        replay_arelle_parse_latency_p90_ms = _coerce_float(
            summary_raw.get("arelle_parse_latency_p90_ms")
        )
        if max_arelle_parse_latency_p90_ms is not None:
            if replay_arelle_parse_latency_p90_ms is None:
                issues.append(
                    "replay_report_arelle_parse_latency_p90_ms_missing_or_invalid"
                )
            elif replay_arelle_parse_latency_p90_ms > max_arelle_parse_latency_p90_ms:
                issues.append("replay_report_arelle_parse_latency_p90_ms_above_max")

        replay_arelle_runtime_lock_wait_p90_ms = _coerce_float(
            summary_raw.get("arelle_runtime_lock_wait_p90_ms")
        )
        if max_arelle_runtime_lock_wait_p90_ms is not None:
            if replay_arelle_runtime_lock_wait_p90_ms is None:
                issues.append(
                    "replay_report_arelle_runtime_lock_wait_p90_ms_missing_or_invalid"
                )
            elif (
                replay_arelle_runtime_lock_wait_p90_ms
                > max_arelle_runtime_lock_wait_p90_ms
            ):
                issues.append("replay_report_arelle_runtime_lock_wait_p90_ms_above_max")

        replay_validation_rule_drift_count = _coerce_int(
            summary_raw.get("validation_rule_drift_count")
        )
        if max_validation_rule_drift_count is not None:
            if replay_validation_rule_drift_count is None:
                issues.append(
                    "replay_report_validation_rule_drift_count_missing_or_invalid"
                )
            elif replay_validation_rule_drift_count > max_validation_rule_drift_count:
                issues.append("replay_report_validation_rule_drift_count_above_max")
    else:
        if max_quality_block_rate is not None:
            issues.append("replay_report_quality_block_rate_missing_or_invalid")
        if min_cache_hit_rate is not None:
            issues.append("replay_report_cache_hit_rate_missing_or_invalid")
        if max_warm_latency_p90_ms is not None:
            issues.append("replay_report_warm_latency_p90_ms_missing_or_invalid")
        if max_cold_latency_p90_ms is not None:
            issues.append("replay_report_cold_latency_p90_ms_missing_or_invalid")
        if max_arelle_parse_latency_p90_ms is not None:
            issues.append(
                "replay_report_arelle_parse_latency_p90_ms_missing_or_invalid"
            )
        if max_arelle_runtime_lock_wait_p90_ms is not None:
            issues.append(
                "replay_report_arelle_runtime_lock_wait_p90_ms_missing_or_invalid"
            )
        if max_validation_rule_drift_count is not None:
            issues.append(
                "replay_report_validation_rule_drift_count_missing_or_invalid"
            )

    return {
        "gate_passed": len(issues) == 0,
        "issues": issues,
        "min_cases": min_cases,
        "min_unique_tickers": min_unique_tickers,
        "min_pass_rate": min_pass_rate,
        "max_intrinsic_delta_p90_abs": max_intrinsic_delta_p90_abs,
        "max_quality_block_rate": max_quality_block_rate,
        "min_cache_hit_rate": min_cache_hit_rate,
        "max_warm_latency_p90_ms": max_warm_latency_p90_ms,
        "max_cold_latency_p90_ms": max_cold_latency_p90_ms,
        "max_arelle_parse_latency_p90_ms": max_arelle_parse_latency_p90_ms,
        "max_arelle_runtime_lock_wait_p90_ms": (max_arelle_runtime_lock_wait_p90_ms),
        "max_validation_rule_drift_count": max_validation_rule_drift_count,
        "require_relative_input_paths": require_relative_input_paths,
        "required_input_root": str(require_input_root) if require_input_root else None,
        "manifest_cases": manifest_cases,
        "manifest_unique_tickers": unique_tickers,
        "manifest_tickers": sorted(tickers),
        "manifest_absolute_input_path_count": invalid_relative_count,
        "manifest_outside_required_root_count": outside_root_count,
        "replay_total_cases": replay_total_cases,
        "replay_failed_cases": replay_failed_cases,
        "replay_pass_rate": replay_pass_rate,
        "replay_intrinsic_delta_available_cases": replay_intrinsic_delta_available_cases,
        "replay_intrinsic_delta_p90_abs": replay_intrinsic_delta_p90_abs,
        "replay_quality_block_rate": replay_quality_block_rate,
        "replay_validation_block_rate": replay_validation_block_rate,
        "replay_cache_hit_rate": replay_cache_hit_rate,
        "replay_warm_latency_p90_ms": replay_warm_latency_p90_ms,
        "replay_cold_latency_p90_ms": replay_cold_latency_p90_ms,
        "replay_arelle_parse_latency_p90_ms": replay_arelle_parse_latency_p90_ms,
        "replay_arelle_runtime_lock_wait_p90_ms": (
            replay_arelle_runtime_lock_wait_p90_ms
        ),
        "replay_validation_rule_drift_count": replay_validation_rule_drift_count,
    }


def _extract_unique_tickers(
    *,
    manifest: ValuationReplayManifestModel,
    manifest_path: Path,
) -> set[str]:
    tickers: set[str] = set()
    for case in manifest.cases:
        input_path = _resolve_input_path(
            manifest_path=manifest_path,
            input_path=case.input_path,
        )
        raw = json.loads(input_path.read_text(encoding="utf-8"))
        replay_input: ValuationReplayInputModel = parse_valuation_replay_input_model(
            raw,
            context=f"cohort.input:{input_path}",
        )
        token = (replay_input.ticker or "").strip().upper()
        if token:
            tickers.add(token)
    return tickers


def _resolve_input_path(*, manifest_path: Path, input_path: str) -> Path:
    path = Path(input_path)
    if path.is_absolute():
        return path
    return (manifest_path.parent / path).resolve()


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _coerce_int(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    return None


def _coerce_float(raw: object) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int | float):
        return float(raw)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
