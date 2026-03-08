from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping
from enum import Enum
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.agents.fundamental.interface.replay_contracts import (  # noqa: E402
    ValuationReplayCaseRefModel,
    ValuationReplayManifestModel,
    parse_valuation_replay_manifest_model,
)
from src.shared.kernel.types import JSONObject  # noqa: E402


class ReplayChecksError(ValueError):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class ReplayChecksErrorCode(str, Enum):
    MANIFEST_FILE_NOT_FOUND = "manifest_file_not_found"
    MANIFEST_INVALID_JSON = "manifest_invalid_json"
    MANIFEST_INVALID_SCHEMA = "manifest_invalid_schema"
    TERMINAL_GROWTH_PATH_MISSING = "terminal_growth_path_missing"
    REPLAY_RUNTIME_ERROR = "replay_runtime_error"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run batch fundamental replay checks using valuation_replay_manifest_v1."
        )
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="Replay manifest JSON path (valuation_replay_manifest_v1).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional output path for aggregated replay check report.",
    )
    parser.add_argument(
        "--abs-tol",
        type=float,
        default=1e-6,
        help="Absolute tolerance passed to replay script.",
    )
    parser.add_argument(
        "--rel-tol",
        type=float,
        default=1e-4,
        help="Relative tolerance passed to replay script.",
    )
    return parser.parse_args()


def _load_manifest(path: Path) -> ValuationReplayManifestModel:
    if not path.exists():
        raise ReplayChecksError(
            f"replay manifest path not found: {path}",
            error_code=ReplayChecksErrorCode.MANIFEST_FILE_NOT_FOUND.value,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReplayChecksError(
            f"replay manifest is not valid JSON: {path} ({exc})",
            error_code=ReplayChecksErrorCode.MANIFEST_INVALID_JSON.value,
        ) from exc
    try:
        return parse_valuation_replay_manifest_model(raw, context="replay.manifest")
    except TypeError as exc:
        raise ReplayChecksError(
            str(exc),
            error_code=ReplayChecksErrorCode.MANIFEST_INVALID_SCHEMA.value,
        ) from exc


def _resolve_input_path(*, manifest_path: Path, input_path: str) -> Path:
    path = Path(input_path)
    if path.is_absolute():
        return path
    return (manifest_path.parent / path).resolve()


def _extract_last_json_object(text: str) -> dict[str, object] | None:
    parsed_objects: list[dict[str, object]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            parsed_objects.append(parsed)
    if not parsed_objects:
        return None
    return parsed_objects[-1]


def _run_replay_case(
    *,
    input_path: Path,
    abs_tol: float,
    rel_tol: float,
) -> tuple[int, dict[str, object] | None]:
    command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "replay_fundamental_valuation.py"),
        "--input",
        str(input_path),
        "--abs-tol",
        str(abs_tol),
        "--rel-tol",
        str(rel_tol),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    payload = _extract_last_json_object(completed.stdout)
    if payload is None:
        payload = _extract_last_json_object(completed.stderr)
    return completed.returncode, payload


def _build_case_result(
    *,
    case: ValuationReplayCaseRefModel,
    input_path: Path,
    return_code: int,
    payload: Mapping[str, object] | None,
) -> JSONObject:
    if return_code == 0 and isinstance(payload, Mapping):
        terminal_growth_path_error = _validate_terminal_growth_path_payload(payload)
        if terminal_growth_path_error is not None:
            return {
                "case_id": case.case_id,
                "input_path": str(input_path),
                "status": "error",
                "error_code": ReplayChecksErrorCode.TERMINAL_GROWTH_PATH_MISSING.value,
                "error": terminal_growth_path_error,
            }
        output: JSONObject = {
            "case_id": case.case_id,
            "input_path": str(input_path),
            "status": "ok",
        }
        intrinsic_delta = payload.get("intrinsic_delta")
        if isinstance(intrinsic_delta, int | float):
            output["intrinsic_delta"] = float(intrinsic_delta)
        return output

    error_code = (
        payload.get("error_code")
        if isinstance(payload, Mapping) and isinstance(payload.get("error_code"), str)
        else ReplayChecksErrorCode.REPLAY_RUNTIME_ERROR.value
    )
    error_message = (
        payload.get("error")
        if isinstance(payload, Mapping) and isinstance(payload.get("error"), str)
        else "replay execution failed"
    )
    return {
        "case_id": case.case_id,
        "input_path": str(input_path),
        "status": "error",
        "error_code": error_code,
        "error": error_message,
    }


def _validate_terminal_growth_path_payload(
    payload: Mapping[str, object],
) -> str | None:
    fallback_mode_raw = payload.get("replayed_terminal_growth_fallback_mode")
    anchor_source_raw = payload.get("replayed_terminal_growth_anchor_source")
    fallback_mode = (
        fallback_mode_raw.strip() if isinstance(fallback_mode_raw, str) else ""
    )
    anchor_source = (
        anchor_source_raw.strip() if isinstance(anchor_source_raw, str) else ""
    )
    if fallback_mode and anchor_source:
        return None
    return (
        "replay output missing terminal-growth path fields: "
        "replayed_terminal_growth_fallback_mode and/or "
        "replayed_terminal_growth_anchor_source"
    )


def _error_code_counts(results: list[JSONObject]) -> JSONObject:
    counts: dict[str, int] = {}
    for item in results:
        if item.get("status") != "error":
            continue
        error_code_raw = item.get("error_code")
        if not isinstance(error_code_raw, str):
            continue
        counts[error_code_raw] = counts.get(error_code_raw, 0) + 1
    return counts


def main() -> int:
    args = parse_args()
    try:
        manifest = _load_manifest(args.manifest)
        results: list[JSONObject] = []
        for case in manifest.cases:
            input_path = _resolve_input_path(
                manifest_path=args.manifest,
                input_path=case.input_path,
            )
            return_code, payload = _run_replay_case(
                input_path=input_path,
                abs_tol=float(args.abs_tol),
                rel_tol=float(args.rel_tol),
            )
            result_item = _build_case_result(
                case=case,
                input_path=input_path,
                return_code=return_code,
                payload=payload,
            )
            results.append(result_item)

        failed_count = sum(1 for item in results if item.get("status") == "error")
        summary: JSONObject = {
            "total_cases": len(results),
            "passed_cases": len(results) - failed_count,
            "failed_cases": failed_count,
            "error_code_counts": _error_code_counts(results),
        }
        report: JSONObject = {
            "schema_version": "fundamental_replay_checks_report_v1",
            "manifest_schema_version": manifest.schema_version,
            "summary": summary,
            "results": results,
        }
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(report, ensure_ascii=False))
        if failed_count > 0:
            return 5
        return 0
    except ReplayChecksError as exc:
        payload = {
            "status": "error",
            "error_code": exc.error_code,
            "error": str(exc),
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 1
    except Exception as exc:  # noqa: BLE001
        payload = {
            "status": "error",
            "error_code": ReplayChecksErrorCode.REPLAY_RUNTIME_ERROR.value,
            "error": str(exc),
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
