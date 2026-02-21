from __future__ import annotations

import argparse
import json
import sys
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = BacktestConfig(abs_tol=args.abs_tol, rel_tol=args.rel_tol)

    if not args.dataset.exists():
        raise FileNotFoundError(f"Backtest dataset not found: {args.dataset}")

    cases = load_cases(args.dataset)
    results = run_cases(cases)

    drifts = []
    issues = []
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
        drifts, issues = compare_with_baseline(results, baseline_cases, config=config)

    report_payload = build_report_payload(
        dataset_path=args.dataset,
        baseline_path=args.baseline,
        results=results,
        drifts=drifts,
        issues=issues,
        baseline_updated=baseline_updated,
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
    if drifts or issues:
        print(
            "[backtest] drift/issues detected: "
            f"drifts={len(drifts)} issues={len(issues)} report={args.report}"
        )
        return 2

    print(f"[backtest] success. report={args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
