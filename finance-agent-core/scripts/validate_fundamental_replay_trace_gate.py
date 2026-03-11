from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate replay trace-contract pass-rate gate.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        required=True,
        help="Path to fundamental replay checks report JSON.",
    )
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        required=True,
        help="Minimum required replay trace-contract pass rate (0~1).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = _read_payload(args.report)
    evaluation = _evaluate(payload=payload, min_pass_rate=float(args.min_pass_rate))
    print(json.dumps(evaluation, ensure_ascii=False))
    if bool(evaluation.get("gate_passed")):
        return 0
    return 1


def _read_payload(path: Path) -> Mapping[str, object]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, Mapping):
        raise TypeError("replay report root must be an object")
    return parsed


def _evaluate(
    *,
    payload: Mapping[str, object],
    min_pass_rate: float,
) -> dict[str, object]:
    summary_raw = payload.get("summary")
    if not isinstance(summary_raw, Mapping):
        return _failed(
            error_code="replay_trace_contract_report_invalid",
            error="summary missing or invalid",
            min_pass_rate=min_pass_rate,
        )

    total_cases = _coerce_int(summary_raw.get("total_cases"))
    passed_cases = _coerce_int(summary_raw.get("passed_cases"))
    failed_cases = _coerce_int(summary_raw.get("failed_cases"))
    if total_cases is None or passed_cases is None or failed_cases is None:
        return _failed(
            error_code="replay_trace_contract_report_invalid",
            error="summary.total_cases/passed_cases/failed_cases missing or invalid",
            min_pass_rate=min_pass_rate,
        )
    if total_cases <= 0:
        return _failed(
            error_code="replay_trace_contract_case_count_invalid",
            error="summary.total_cases must be > 0",
            min_pass_rate=min_pass_rate,
            total_cases=total_cases,
            passed_cases=passed_cases,
            failed_cases=failed_cases,
        )

    pass_rate = _coerce_float(summary_raw.get("trace_contract_pass_rate"))
    if pass_rate is None:
        pass_rate = passed_cases / total_cases

    gate_passed = pass_rate >= min_pass_rate
    output: dict[str, object] = {
        "gate_passed": gate_passed,
        "error_code": None
        if gate_passed
        else "replay_trace_contract_pass_rate_below_min",
        "error": None
        if gate_passed
        else (
            "trace_contract_pass_rate below minimum "
            f"({pass_rate:.6f} < {min_pass_rate:.6f})"
        ),
        "min_pass_rate": min_pass_rate,
        "observed_pass_rate": pass_rate,
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": failed_cases,
    }
    return output


def _failed(
    *,
    error_code: str,
    error: str,
    min_pass_rate: float,
    total_cases: int | None = None,
    passed_cases: int | None = None,
    failed_cases: int | None = None,
) -> dict[str, object]:
    return {
        "gate_passed": False,
        "error_code": error_code,
        "error": error,
        "min_pass_rate": min_pass_rate,
        "observed_pass_rate": None,
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "failed_cases": failed_cases,
    }


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
