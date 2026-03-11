from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.agents.fundamental.interface.replay_contracts import (  # noqa: E402
    ValuationReplayCaseRefModel,
    ValuationReplayInputModel,
    ValuationReplayManifestModel,
    parse_valuation_replay_input_model,
    parse_valuation_replay_manifest_model,
)
from src.shared.kernel.types import JSONObject  # noqa: E402

_QUALITY_BLOCK_ERROR_CODE = "FUNDAMENTAL_XBRL_QUALITY_BLOCKED"
_VALIDATION_MODE_ENV = "FUNDAMENTAL_XBRL_ARELLE_VALIDATION_MODE"
_DISCLOSURE_SYSTEM_ENV = "FUNDAMENTAL_XBRL_ARELLE_DISCLOSURE_SYSTEM"
_PLUGINS_ENV = "FUNDAMENTAL_XBRL_ARELLE_PLUGINS"
_PACKAGES_ENV = "FUNDAMENTAL_XBRL_ARELLE_PACKAGES"
_EXPECTED_RULE_SIGNATURE_ENV = "FUNDAMENTAL_XBRL_EXPECTED_RULE_SIGNATURE"
_VALIDATION_RULE_DRIFT_ERROR_CODE = "validation_rule_version_drift"


class ReplayChecksError(ValueError):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class ReplayChecksErrorCode(str, Enum):
    MANIFEST_FILE_NOT_FOUND = "manifest_file_not_found"
    MANIFEST_INVALID_JSON = "manifest_invalid_json"
    MANIFEST_INVALID_SCHEMA = "manifest_invalid_schema"
    TERMINAL_GROWTH_PATH_MISSING = "terminal_growth_path_missing"
    FORWARD_SIGNAL_TRACE_MISSING = "forward_signal_trace_missing"
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


def _load_replay_input(
    *,
    input_path: Path,
) -> ValuationReplayInputModel | None:
    try:
        raw = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return parse_valuation_replay_input_model(
            raw, context=f"replay.input:{input_path}"
        )
    except TypeError:
        return None


def _extract_case_hints(
    replay_input: ValuationReplayInputModel | None,
) -> JSONObject:
    if replay_input is None or replay_input.baseline is None:
        return {}

    hints: JSONObject = {}
    baseline = replay_input.baseline
    diagnostics = (
        baseline.diagnostics if isinstance(baseline.diagnostics, Mapping) else None
    )
    if isinstance(diagnostics, Mapping):
        cache_raw = diagnostics.get("cache")
        if isinstance(cache_raw, Mapping):
            cache_hit = _coerce_bool(cache_raw.get("cache_hit"))
            if cache_hit is not None:
                hints["xbrl_cache_hit"] = cache_hit
            total_latency_ms = _coerce_float(cache_raw.get("total_latency_ms"))
            if total_latency_ms is not None:
                hints["xbrl_total_latency_ms"] = total_latency_ms
        arelle_runtime = _extract_arelle_runtime(diagnostics)
        if isinstance(arelle_runtime, Mapping):
            arelle_parse_latency_ms = _coerce_first_float(
                arelle_runtime,
                keys=(
                    "parse_latency_ms_avg",
                    "parse_latency_ms_p90",
                    "parse_latency_ms",
                ),
            )
            if arelle_parse_latency_ms is not None:
                hints["arelle_parse_latency_ms"] = arelle_parse_latency_ms
            arelle_runtime_lock_wait_ms = _coerce_first_float(
                arelle_runtime,
                keys=(
                    "runtime_lock_wait_ms_avg",
                    "runtime_lock_wait_ms_p90",
                    "runtime_lock_wait_ms",
                ),
            )
            if arelle_runtime_lock_wait_ms is not None:
                hints["arelle_runtime_lock_wait_ms"] = arelle_runtime_lock_wait_ms
            arelle_runtime_isolation_mode = _extract_arelle_runtime_isolation_mode(
                arelle_runtime
            )
            if arelle_runtime_isolation_mode is not None:
                hints["arelle_runtime_isolation_mode"] = arelle_runtime_isolation_mode

    build_metadata = (
        baseline.build_metadata
        if isinstance(baseline.build_metadata, Mapping)
        else None
    )
    quality_status = _extract_quality_status(build_metadata)
    if quality_status is not None:
        hints["xbrl_quality_status"] = quality_status
    quality_blocked = _extract_quality_blocked(build_metadata)
    if quality_blocked is not None:
        hints["quality_blocked"] = quality_blocked

    return hints


def _build_case_result(
    *,
    case: ValuationReplayCaseRefModel,
    input_path: Path,
    return_code: int,
    payload: Mapping[str, object] | None,
    runtime_duration_ms: float,
    case_hints: Mapping[str, object] | None,
) -> JSONObject:
    quality_status = _extract_quality_status(payload)
    if quality_status is None and isinstance(case_hints, Mapping):
        quality_status = _coerce_text(case_hints.get("xbrl_quality_status"))

    quality_blocked = _extract_quality_blocked(payload)
    if quality_blocked is None and isinstance(case_hints, Mapping):
        quality_blocked = _coerce_bool(case_hints.get("quality_blocked"))

    cache_hit = _extract_cache_hit(payload)
    if cache_hit is None and isinstance(case_hints, Mapping):
        cache_hit = _coerce_bool(case_hints.get("xbrl_cache_hit"))

    xbrl_total_latency_ms = _extract_total_latency_ms(payload)
    if xbrl_total_latency_ms is None and isinstance(case_hints, Mapping):
        xbrl_total_latency_ms = _coerce_float(case_hints.get("xbrl_total_latency_ms"))

    arelle_parse_latency_ms = _extract_arelle_parse_latency_ms(payload)
    if arelle_parse_latency_ms is None and isinstance(case_hints, Mapping):
        arelle_parse_latency_ms = _coerce_float(
            case_hints.get("arelle_parse_latency_ms")
        )

    arelle_runtime_lock_wait_ms = _extract_arelle_runtime_lock_wait_ms(payload)
    if arelle_runtime_lock_wait_ms is None and isinstance(case_hints, Mapping):
        arelle_runtime_lock_wait_ms = _coerce_float(
            case_hints.get("arelle_runtime_lock_wait_ms")
        )

    arelle_runtime_isolation_mode = _extract_arelle_runtime_isolation_mode(payload)
    if arelle_runtime_isolation_mode is None and isinstance(case_hints, Mapping):
        arelle_runtime_isolation_mode = _coerce_text(
            case_hints.get("arelle_runtime_isolation_mode")
        )

    latency_ms = xbrl_total_latency_ms
    latency_source = "xbrl_total_latency_ms"
    if latency_ms is None:
        latency_ms = runtime_duration_ms
        latency_source = "replay_duration_ms"

    output: JSONObject = {
        "case_id": case.case_id,
        "input_path": str(input_path),
        "replay_duration_ms": runtime_duration_ms,
        "latency_ms": latency_ms,
        "latency_source": latency_source,
    }
    if cache_hit is not None:
        output["xbrl_cache_hit"] = cache_hit
    if xbrl_total_latency_ms is not None:
        output["xbrl_total_latency_ms"] = xbrl_total_latency_ms
    if arelle_parse_latency_ms is not None:
        output["arelle_parse_latency_ms"] = arelle_parse_latency_ms
    if arelle_runtime_lock_wait_ms is not None:
        output["arelle_runtime_lock_wait_ms"] = arelle_runtime_lock_wait_ms
    if arelle_runtime_isolation_mode is not None:
        output["arelle_runtime_isolation_mode"] = arelle_runtime_isolation_mode
    if quality_status is not None:
        output["xbrl_quality_status"] = quality_status

    if return_code == 0 and isinstance(payload, Mapping):
        terminal_growth_path_error = _validate_terminal_growth_path_payload(payload)
        if terminal_growth_path_error is not None:
            output.update(
                {
                    "status": "error",
                    "error_code": ReplayChecksErrorCode.TERMINAL_GROWTH_PATH_MISSING.value,
                    "error": terminal_growth_path_error,
                }
            )
            if quality_blocked is not None:
                output["quality_blocked"] = quality_blocked
            return output

        forward_signal_trace_error = _validate_forward_signal_trace_payload(payload)
        if forward_signal_trace_error is not None:
            output.update(
                {
                    "status": "error",
                    "error_code": ReplayChecksErrorCode.FORWARD_SIGNAL_TRACE_MISSING.value,
                    "error": forward_signal_trace_error,
                }
            )
            if quality_blocked is not None:
                output["quality_blocked"] = quality_blocked
            return output

        output.update(
            {
                "status": "ok",
                "trace_contract_passed": True,
            }
        )
        intrinsic_delta = payload.get("intrinsic_delta")
        if isinstance(intrinsic_delta, int | float):
            output["intrinsic_delta"] = float(intrinsic_delta)
        delta_by_parameter_group_raw = payload.get("delta_by_parameter_group")
        if isinstance(delta_by_parameter_group_raw, Mapping):
            output["delta_by_parameter_group"] = dict(delta_by_parameter_group_raw)
        if quality_blocked is not None:
            output["quality_blocked"] = quality_blocked
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
    output.update(
        {
            "status": "error",
            "error_code": error_code,
            "error": error_message,
        }
    )
    if quality_blocked is None:
        quality_blocked = error_code == _QUALITY_BLOCK_ERROR_CODE
    if quality_blocked is not None:
        output["quality_blocked"] = quality_blocked
    return output


def _validate_terminal_growth_path_payload(
    payload: Mapping[str, object],
) -> str | None:
    model_type_raw = payload.get("model_type")
    model_type = (
        model_type_raw.strip().lower() if isinstance(model_type_raw, str) else ""
    )
    if model_type == "bank":
        return None

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


def _validate_forward_signal_trace_payload(payload: Mapping[str, object]) -> str | None:
    forward_signal_raw = payload.get("replayed_forward_signal")
    if not isinstance(forward_signal_raw, Mapping):
        return "replay output missing replayed_forward_signal object"

    calibration_applied_raw = forward_signal_raw.get("calibration_applied")
    if not isinstance(calibration_applied_raw, bool):
        return (
            "replay output missing replayed_forward_signal.calibration_applied boolean"
        )

    mapping_version_raw = forward_signal_raw.get("mapping_version")
    if not isinstance(mapping_version_raw, str) or not mapping_version_raw.strip():
        return "replay output missing replayed_forward_signal.mapping_version"

    for key in (
        "growth_adjustment_basis_points",
        "margin_adjustment_basis_points",
        "raw_growth_adjustment_basis_points",
        "raw_margin_adjustment_basis_points",
    ):
        raw_value = forward_signal_raw.get(key)
        if not isinstance(raw_value, int | float) or isinstance(raw_value, bool):
            return f"replay output missing replayed_forward_signal.{key} numeric value"

    if "calibration_degraded_reason" not in forward_signal_raw:
        return (
            "replay output missing replayed_forward_signal.calibration_degraded_reason"
        )
    degraded_reason_raw = forward_signal_raw.get("calibration_degraded_reason")
    if degraded_reason_raw is not None and not isinstance(degraded_reason_raw, str):
        return (
            "replay output invalid replayed_forward_signal.calibration_degraded_reason"
        )
    return None


def _extract_quality_status(payload: Mapping[str, object] | None) -> str | None:
    if not isinstance(payload, Mapping):
        return None

    quality_status = _coerce_text(payload.get("xbrl_quality_status"))
    if quality_status is not None:
        return quality_status.lower()

    quality_gates_raw = payload.get("xbrl_quality_gates")
    if not isinstance(quality_gates_raw, Mapping):
        quality_gates_raw = payload.get("quality_gates")
    if isinstance(quality_gates_raw, Mapping):
        quality_status = _coerce_text(quality_gates_raw.get("status"))
        if quality_status is not None:
            return quality_status.lower()

    return None


def _extract_quality_blocked(payload: Mapping[str, object] | None) -> bool | None:
    status = _extract_quality_status(payload)
    if status is not None:
        return status == "block"

    if not isinstance(payload, Mapping):
        return None

    quality_blocked = _coerce_bool(payload.get("quality_blocked"))
    if quality_blocked is not None:
        return quality_blocked

    quality_gates_raw = payload.get("xbrl_quality_gates")
    if not isinstance(quality_gates_raw, Mapping):
        quality_gates_raw = payload.get("quality_gates")
    if isinstance(quality_gates_raw, Mapping):
        blocking_count = _coerce_float(quality_gates_raw.get("blocking_count"))
        if blocking_count is not None:
            return blocking_count > 0

    return None


def _extract_cache_hit(payload: Mapping[str, object] | None) -> bool | None:
    if not isinstance(payload, Mapping):
        return None

    cache_hit = _coerce_bool(payload.get("xbrl_cache_hit"))
    if cache_hit is not None:
        return cache_hit

    diagnostics_raw = payload.get("xbrl_diagnostics")
    if not isinstance(diagnostics_raw, Mapping):
        diagnostics_raw = payload.get("diagnostics")
    if isinstance(diagnostics_raw, Mapping):
        cache_raw = diagnostics_raw.get("cache")
        if isinstance(cache_raw, Mapping):
            return _coerce_bool(cache_raw.get("cache_hit"))

    return None


def _extract_total_latency_ms(payload: Mapping[str, object] | None) -> float | None:
    if not isinstance(payload, Mapping):
        return None

    total_latency_ms = _coerce_float(payload.get("xbrl_total_latency_ms"))
    if total_latency_ms is not None:
        return total_latency_ms

    diagnostics_raw = payload.get("xbrl_diagnostics")
    if not isinstance(diagnostics_raw, Mapping):
        diagnostics_raw = payload.get("diagnostics")
    if isinstance(diagnostics_raw, Mapping):
        cache_raw = diagnostics_raw.get("cache")
        if isinstance(cache_raw, Mapping):
            return _coerce_float(cache_raw.get("total_latency_ms"))

    return None


def _extract_arelle_parse_latency_ms(
    payload: Mapping[str, object] | None,
) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    direct = _coerce_float(payload.get("arelle_parse_latency_ms"))
    if direct is not None:
        return direct

    arelle_runtime = _extract_arelle_runtime(payload)
    if not isinstance(arelle_runtime, Mapping):
        return None
    return _coerce_first_float(
        arelle_runtime,
        keys=("parse_latency_ms_avg", "parse_latency_ms_p90", "parse_latency_ms"),
    )


def _extract_arelle_runtime_lock_wait_ms(
    payload: Mapping[str, object] | None,
) -> float | None:
    if not isinstance(payload, Mapping):
        return None
    direct = _coerce_float(payload.get("arelle_runtime_lock_wait_ms"))
    if direct is not None:
        return direct

    arelle_runtime = _extract_arelle_runtime(payload)
    if not isinstance(arelle_runtime, Mapping):
        return None
    return _coerce_first_float(
        arelle_runtime,
        keys=(
            "runtime_lock_wait_ms_avg",
            "runtime_lock_wait_ms_p90",
            "runtime_lock_wait_ms",
        ),
    )


def _extract_arelle_runtime_isolation_mode(
    payload: Mapping[str, object] | None,
) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    direct = _coerce_text(payload.get("arelle_runtime_isolation_mode"))
    if direct is not None:
        return direct

    isolation_modes_raw = payload.get("isolation_modes")
    if isinstance(isolation_modes_raw, Sequence) and not isinstance(
        isolation_modes_raw, str | bytes
    ):
        for item in isolation_modes_raw:
            token = _coerce_text(item)
            if token is not None:
                return token

    arelle_runtime = _extract_arelle_runtime(payload)
    if not isinstance(arelle_runtime, Mapping):
        return None

    runtime_isolation_mode = _coerce_text(arelle_runtime.get("runtime_isolation_mode"))
    if runtime_isolation_mode is not None:
        return runtime_isolation_mode

    isolation_modes_raw = arelle_runtime.get("isolation_modes")
    if isinstance(isolation_modes_raw, Sequence) and not isinstance(
        isolation_modes_raw, str | bytes
    ):
        for item in isolation_modes_raw:
            token = _coerce_text(item)
            if token is not None:
                return token
    return None


def _extract_arelle_runtime(
    payload: Mapping[str, object],
) -> Mapping[str, object] | None:
    direct = payload.get("arelle_runtime")
    if isinstance(direct, Mapping):
        return direct

    diagnostics_raw = payload.get("xbrl_diagnostics")
    if not isinstance(diagnostics_raw, Mapping):
        diagnostics_raw = payload.get("diagnostics")
    if not isinstance(diagnostics_raw, Mapping):
        return None

    runtime = diagnostics_raw.get("arelle_runtime")
    if isinstance(runtime, Mapping):
        return runtime
    return None


def _coerce_first_float(
    payload: Mapping[str, object],
    *,
    keys: Sequence[str],
) -> float | None:
    for key in keys:
        value = _coerce_float(payload.get(key))
        if value is not None:
            return value
    return None


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _coerce_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip()
    if not token:
        return None
    return token


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


def _extract_intrinsic_delta_values(results: Sequence[JSONObject]) -> list[float]:
    values: list[float] = []
    for item in results:
        if item.get("status") != "ok":
            continue
        intrinsic_delta_raw = item.get("intrinsic_delta")
        if isinstance(intrinsic_delta_raw, bool):
            continue
        if isinstance(intrinsic_delta_raw, int | float):
            values.append(float(intrinsic_delta_raw))
    return values


def _extract_quality_blocked_count(results: Sequence[JSONObject]) -> int:
    blocked = 0
    for item in results:
        quality_blocked = _coerce_bool(item.get("quality_blocked"))
        if quality_blocked is True:
            blocked += 1
            continue
        error_code = item.get("error_code")
        if isinstance(error_code, str) and error_code == _QUALITY_BLOCK_ERROR_CODE:
            blocked += 1
    return blocked


def _extract_cache_hit_count(results: Sequence[JSONObject]) -> int:
    return sum(
        1 for item in results if _coerce_bool(item.get("xbrl_cache_hit")) is True
    )


def _extract_latency_groups(
    results: Sequence[JSONObject],
) -> tuple[list[float], list[float]]:
    warm: list[float] = []
    cold: list[float] = []
    for item in results:
        latency_ms = _coerce_float(item.get("latency_ms"))
        if latency_ms is None:
            continue
        cache_hit = _coerce_bool(item.get("xbrl_cache_hit"))
        if cache_hit is True:
            warm.append(latency_ms)
        else:
            cold.append(latency_ms)
    return warm, cold


def _extract_xbrl_latency_values(results: Sequence[JSONObject]) -> list[float]:
    values: list[float] = []
    for item in results:
        latency_ms = _coerce_float(item.get("xbrl_total_latency_ms"))
        if latency_ms is None:
            continue
        values.append(latency_ms)
    return values


def _extract_runtime_durations(results: Sequence[JSONObject]) -> list[float]:
    values: list[float] = []
    for item in results:
        duration_ms = _coerce_float(item.get("replay_duration_ms"))
        if duration_ms is None:
            continue
        values.append(duration_ms)
    return values


def _extract_arelle_parse_latency_values(results: Sequence[JSONObject]) -> list[float]:
    values: list[float] = []
    for item in results:
        value = _coerce_float(item.get("arelle_parse_latency_ms"))
        if value is not None:
            values.append(value)
    return values


def _extract_arelle_runtime_lock_wait_values(
    results: Sequence[JSONObject],
) -> list[float]:
    values: list[float] = []
    for item in results:
        value = _coerce_float(item.get("arelle_runtime_lock_wait_ms"))
        if value is not None:
            values.append(value)
    return values


def _extract_arelle_runtime_isolation_mode_counts(
    results: Sequence[JSONObject],
) -> JSONObject:
    counts: dict[str, int] = {}
    for item in results:
        token = _coerce_text(item.get("arelle_runtime_isolation_mode"))
        if token is None:
            continue
        counts[token] = counts.get(token, 0) + 1
    return counts


def _safe_rate(*, numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _build_latency_stats(
    values: Sequence[float],
) -> tuple[int, float | None, float | None]:
    if not values:
        return 0, None, None
    sorted_values = sorted(values)
    return (
        len(sorted_values),
        _percentile(sorted_values, 50.0),
        _percentile(sorted_values, 90.0),
    )


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


def _normalize_csv_tokens(raw: str) -> list[str]:
    if not raw.strip():
        return []
    values = [token.strip() for token in raw.split(",") if token.strip()]
    return sorted(set(values))


def _resolve_arelle_version() -> str | None:
    for package_name in ("arelle-release", "arelle"):
        try:
            token = importlib.metadata.version(package_name).strip()
        except importlib.metadata.PackageNotFoundError:
            continue
        if token:
            return token
    return None


def _build_validation_rule_runtime_evidence() -> JSONObject:
    validation_mode_raw = os.getenv(_VALIDATION_MODE_ENV, "").strip().lower()
    validation_mode = validation_mode_raw or "facts_only"
    disclosure_system_raw = os.getenv(_DISCLOSURE_SYSTEM_ENV, "").strip()
    disclosure_system = disclosure_system_raw or None
    if validation_mode != "facts_only" and disclosure_system is None:
        disclosure_system = "efm"

    plugins = _normalize_csv_tokens(os.getenv(_PLUGINS_ENV, ""))
    packages = _normalize_csv_tokens(os.getenv(_PACKAGES_ENV, ""))
    arelle_version = _resolve_arelle_version()
    signature_payload = {
        "validation_mode": validation_mode,
        "disclosure_system": disclosure_system,
        "plugins": plugins,
        "packages": packages,
        "arelle_version": arelle_version,
    }
    signature = json.dumps(signature_payload, ensure_ascii=False, sort_keys=True)
    return {
        "signature": signature,
        "validation_mode": validation_mode,
        "disclosure_system": disclosure_system,
        "plugins": plugins,
        "packages": packages,
        "arelle_version": arelle_version,
    }


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
            replay_input = _load_replay_input(input_path=input_path)
            case_hints = _extract_case_hints(replay_input)
            started = time.perf_counter()
            return_code, payload = _run_replay_case(
                input_path=input_path,
                abs_tol=float(args.abs_tol),
                rel_tol=float(args.rel_tol),
            )
            runtime_duration_ms = round((time.perf_counter() - started) * 1000.0, 3)
            result_item = _build_case_result(
                case=case,
                input_path=input_path,
                return_code=return_code,
                payload=payload,
                runtime_duration_ms=runtime_duration_ms,
                case_hints=case_hints,
            )
            results.append(result_item)

        failed_count = sum(1 for item in results if item.get("status") == "error")
        passed_count = len(results) - failed_count
        trace_contract_pass_count = sum(
            1
            for item in results
            if item.get("status") == "ok" and item.get("trace_contract_passed") is True
        )
        trace_contract_pass_rate = (
            trace_contract_pass_count / len(results) if results else 0.0
        )
        intrinsic_delta_values = _extract_intrinsic_delta_values(results)
        intrinsic_delta_abs_values = sorted(
            abs(value) for value in intrinsic_delta_values
        )
        quality_blocked_count = _extract_quality_blocked_count(results)
        cache_hit_count = _extract_cache_hit_count(results)
        warm_latency_values, cold_latency_values = _extract_latency_groups(results)
        warm_latency_count, warm_latency_p50, warm_latency_p90 = _build_latency_stats(
            warm_latency_values
        )
        cold_latency_count, cold_latency_p50, cold_latency_p90 = _build_latency_stats(
            cold_latency_values
        )
        xbrl_latency_values = _extract_xbrl_latency_values(results)
        xbrl_latency_count, xbrl_latency_p50, xbrl_latency_p90 = _build_latency_stats(
            xbrl_latency_values
        )
        replay_duration_values = _extract_runtime_durations(results)
        replay_duration_count, replay_duration_p50, replay_duration_p90 = (
            _build_latency_stats(replay_duration_values)
        )
        validation_rule_runtime = _build_validation_rule_runtime_evidence()
        validation_rule_actual_signature = _coerce_text(
            validation_rule_runtime.get("signature")
        )
        validation_rule_expected_signature = _coerce_text(
            os.getenv(_EXPECTED_RULE_SIGNATURE_ENV, "")
        )
        validation_rule_drift_detected = (
            validation_rule_expected_signature is not None
            and validation_rule_actual_signature is not None
            and validation_rule_expected_signature != validation_rule_actual_signature
        )
        validation_rule_drift_count = 1 if validation_rule_drift_detected else 0
        arelle_parse_latency_values = _extract_arelle_parse_latency_values(results)
        (
            arelle_parse_latency_count,
            arelle_parse_latency_p50,
            arelle_parse_latency_p90,
        ) = _build_latency_stats(arelle_parse_latency_values)
        arelle_runtime_lock_wait_values = _extract_arelle_runtime_lock_wait_values(
            results
        )
        (
            arelle_runtime_lock_wait_count,
            arelle_runtime_lock_wait_p50,
            arelle_runtime_lock_wait_p90,
        ) = _build_latency_stats(arelle_runtime_lock_wait_values)
        arelle_runtime_isolation_mode_counts = (
            _extract_arelle_runtime_isolation_mode_counts(results)
        )

        summary: JSONObject = {
            "total_cases": len(results),
            "passed_cases": passed_count,
            "failed_cases": failed_count,
            "trace_contract_passed_cases": trace_contract_pass_count,
            "trace_contract_pass_rate": trace_contract_pass_rate,
            "error_code_counts": _error_code_counts(results),
            "intrinsic_delta_available_cases": len(intrinsic_delta_values),
            "intrinsic_delta_p90_abs": (
                _percentile(intrinsic_delta_abs_values, 90.0)
                if intrinsic_delta_abs_values
                else None
            ),
            "quality_blocked_cases": quality_blocked_count,
            "quality_block_rate": _safe_rate(
                numerator=quality_blocked_count,
                denominator=len(results),
            ),
            "validation_blocked_cases": quality_blocked_count,
            "validation_block_rate": _safe_rate(
                numerator=quality_blocked_count,
                denominator=len(results),
            ),
            "cache_hit_cases": cache_hit_count,
            "cache_hit_rate": _safe_rate(
                numerator=cache_hit_count,
                denominator=len(results),
            ),
            "warm_latency_available_cases": warm_latency_count,
            "warm_latency_p50_ms": warm_latency_p50,
            "warm_latency_p90_ms": warm_latency_p90,
            "cold_latency_available_cases": cold_latency_count,
            "cold_latency_p50_ms": cold_latency_p50,
            "cold_latency_p90_ms": cold_latency_p90,
            "xbrl_latency_available_cases": xbrl_latency_count,
            "xbrl_latency_p50_ms": xbrl_latency_p50,
            "xbrl_latency_p90_ms": xbrl_latency_p90,
            "replay_duration_available_cases": replay_duration_count,
            "replay_duration_p50_ms": replay_duration_p50,
            "replay_duration_p90_ms": replay_duration_p90,
            "arelle_parse_latency_available_cases": arelle_parse_latency_count,
            "arelle_parse_latency_p50_ms": arelle_parse_latency_p50,
            "arelle_parse_latency_p90_ms": arelle_parse_latency_p90,
            "arelle_runtime_lock_wait_available_cases": arelle_runtime_lock_wait_count,
            "arelle_runtime_lock_wait_p50_ms": arelle_runtime_lock_wait_p50,
            "arelle_runtime_lock_wait_p90_ms": arelle_runtime_lock_wait_p90,
            "arelle_runtime_isolation_mode_counts": arelle_runtime_isolation_mode_counts,
            "validation_rule_runtime": validation_rule_runtime,
            "validation_rule_actual_signature": validation_rule_actual_signature,
            "validation_rule_expected_signature": validation_rule_expected_signature,
            "validation_rule_drift_count": validation_rule_drift_count,
            "validation_rule_drift_detected": validation_rule_drift_detected,
            "validation_rule_drift_error_code": (
                _VALIDATION_RULE_DRIFT_ERROR_CODE
                if validation_rule_drift_detected
                else None
            ),
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
