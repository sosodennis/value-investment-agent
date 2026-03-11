from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Mapping
from enum import Enum
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.agents.fundamental.domain.valuation.parameterization.orchestrator import (  # noqa: E402
    build_params,
)
from src.agents.fundamental.domain.valuation.valuation_model_registry import (  # noqa: E402
    ValuationModelRegistry,
)
from src.agents.fundamental.infrastructure.market_data.market_data_service import (  # noqa: E402
    recompute_market_snapshot_staleness,
)
from src.agents.fundamental.interface.contracts import (  # noqa: E402
    parse_financial_reports_model,
)
from src.agents.fundamental.interface.parsers import (  # noqa: E402
    parse_calculation_metrics,
    parse_valuation_model_runtime,
)
from src.agents.fundamental.interface.replay_contracts import (  # noqa: E402
    ValuationReplayInputModel,
    parse_valuation_replay_input_model,
)
from src.shared.kernel.types import JSONObject  # noqa: E402

_NUMERIC_PATTERN = r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
_PARAMETER_GROUP_FIELDS: dict[str, tuple[str, ...]] = {
    "growth": ("growth_rates",),
    "margin": ("operating_margins",),
    "reinvestment": ("capex_rates", "wc_rates", "sbc_rates"),
    "terminal": ("terminal_growth",),
}
_GUARDRAIL_APPLIED_PATTERN = re.compile(
    r"^base_(?P<kind>growth|margin)_guardrail applied "
    r"\(version=(?P<version>[^,]+), "
    r"profile=(?P<profile>[^,]+), "
    r"raw_year1=(?P<raw_year1>"
    + _NUMERIC_PATTERN
    + r"), raw_yearN=(?P<raw_yearN>"
    + _NUMERIC_PATTERN
    + r"), guarded_year1=(?P<guarded_year1>"
    + _NUMERIC_PATTERN
    + r"), guarded_yearN=(?P<guarded_yearN>"
    + _NUMERIC_PATTERN
    + r"), reasons=(?P<reasons>[^)]+)\)$"
)
_REINVESTMENT_GUARDRAIL_APPLIED_PATTERN = re.compile(
    r"^base_reinvestment_guardrail applied "
    r"\(version=(?P<version>[^,]+), "
    r"profile=(?P<profile>[^,]+), "
    r"metric=(?P<metric>[^,]+), "
    r"raw_year1=(?P<raw_year1>"
    + _NUMERIC_PATTERN
    + r"), raw_yearN=(?P<raw_yearN>"
    + _NUMERIC_PATTERN
    + r"), guarded_year1=(?P<guarded_year1>"
    + _NUMERIC_PATTERN
    + r"), guarded_yearN=(?P<guarded_yearN>"
    + _NUMERIC_PATTERN
    + r"), anchor=(?P<anchor>[^,]+), anchor_samples=(?P<anchor_samples>\d+), "
    r"reasons=(?P<reasons>[^)]+)\)$"
)
_CONSENSUS_DECAY_WINDOW_PATTERN = re.compile(
    r"^consensus_growth_rate decayed into near-term DCF growth path "
    r"\(horizon=[^,]+, window_years=(?P<window>\d+),"
)
_TERMINAL_GROWTH_FALLBACK_MODE_PATTERN = re.compile(
    r"^terminal_growth stale fallback mode=(?P<mode>[a-z_]+)$"
)
_TERMINAL_GROWTH_ANCHOR_SOURCE_PATTERN = re.compile(
    r"^terminal_growth anchor source=(?P<source>[a-z_]+)$"
)


class ReplayContractError(ValueError):
    def __init__(self, message: str, *, error_code: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class ReplayErrorCode(str, Enum):
    REPLAY_INPUT_FILE_NOT_FOUND = "replay_input_file_not_found"
    REPLAY_INPUT_INVALID_JSON = "replay_input_invalid_json"
    INVALID_REPLAY_INPUT_SCHEMA = "invalid_replay_input_schema"
    REPLAY_OVERRIDE_FILE_NOT_FOUND = "replay_override_file_not_found"
    REPLAY_OVERRIDE_INVALID_JSON = "replay_override_invalid_json"
    REPLAY_OVERRIDE_INVALID_SCHEMA = "replay_override_invalid_schema"
    PAYLOAD_CONTRACT_INVALID = "payload_contract_invalid"
    PARAM_BUILD_MISSING_INPUTS = "param_build_missing_inputs"
    LEGACY_PAYLOAD_NOT_SUPPORTED = "legacy_payload_not_supported"
    REPLAY_OUTPUT_INVALID = "replay_output_invalid"
    REPLAY_RUNTIME_ERROR = "replay_runtime_error"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Replay a fundamental valuation run from structured replay input "
            "contract (valuation_replay_input_v2)."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Replay input JSON path (valuation_replay_input_v2).",
    )
    parser.add_argument(
        "--override-json",
        type=Path,
        default=None,
        help="Optional replay override JSON path. Deep-merged after input override.",
    )
    parser.add_argument(
        "--abs-tol",
        type=float,
        default=1e-6,
        help="Absolute tolerance for drift check.",
    )
    parser.add_argument(
        "--rel-tol",
        type=float,
        default=1e-4,
        help="Relative tolerance for drift check.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional output JSON report path.",
    )
    return parser.parse_args()


def _load_replay_input(path: Path) -> ValuationReplayInputModel:
    if not path.exists():
        raise ReplayContractError(
            f"replay input path not found: {path}",
            error_code=ReplayErrorCode.REPLAY_INPUT_FILE_NOT_FOUND.value,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReplayContractError(
            f"replay input is not valid JSON: {path} ({exc})",
            error_code=ReplayErrorCode.REPLAY_INPUT_INVALID_JSON.value,
        ) from exc
    try:
        return parse_valuation_replay_input_model(raw, context="replay.input")
    except TypeError as exc:
        raise ReplayContractError(
            str(exc),
            error_code=ReplayErrorCode.INVALID_REPLAY_INPUT_SCHEMA.value,
        ) from exc


def _load_override_input(path: Path | None) -> dict[str, object] | None:
    if path is None:
        return None
    if not path.exists():
        raise ReplayContractError(
            f"replay override path not found: {path}",
            error_code=ReplayErrorCode.REPLAY_OVERRIDE_FILE_NOT_FOUND.value,
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ReplayContractError(
            f"replay override is not valid JSON: {path} ({exc})",
            error_code=ReplayErrorCode.REPLAY_OVERRIDE_INVALID_JSON.value,
        ) from exc
    if not isinstance(raw, dict):
        raise ReplayContractError(
            "replay override payload must be a JSON object",
            error_code=ReplayErrorCode.REPLAY_OVERRIDE_INVALID_SCHEMA.value,
        )
    return dict(raw)


def _deep_merge(
    base: Mapping[str, object],
    override: Mapping[str, object],
) -> JSONObject:
    merged: JSONObject = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
            continue
        merged[key] = value
    return merged


def _effective_override_payload(
    replay_input: ValuationReplayInputModel,
    *,
    cli_override: Mapping[str, object] | None,
) -> JSONObject:
    payload: JSONObject = {}
    if isinstance(replay_input.override, Mapping):
        payload = _deep_merge(payload, replay_input.override)
    if isinstance(cli_override, Mapping):
        payload = _deep_merge(payload, cli_override)
    return payload


def _apply_replay_override(
    replay_input: ValuationReplayInputModel,
    *,
    override_payload: Mapping[str, object],
) -> ValuationReplayInputModel:
    if not override_payload:
        return replay_input
    baseline = replay_input.model_dump(mode="json", exclude_none=False)
    merged = _deep_merge(baseline, override_payload)
    merged["override"] = None
    try:
        return parse_valuation_replay_input_model(
            merged, context="replay.input.override"
        )
    except TypeError as exc:
        raise ReplayContractError(
            str(exc),
            error_code=ReplayErrorCode.REPLAY_OVERRIDE_INVALID_SCHEMA.value,
        ) from exc


def _recompute_market_staleness(
    market_snapshot: Mapping[str, object] | None,
) -> JSONObject | None:
    return recompute_market_snapshot_staleness(market_snapshot)


def _read_numeric(raw: object) -> float | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    return None


def _is_within_tolerance(
    *,
    actual: float,
    expected: float,
    abs_tol: float,
    rel_tol: float,
) -> bool:
    diff = abs(actual - expected)
    allowed = max(abs_tol, rel_tol * max(abs(expected), 1.0))
    return diff <= allowed


def _extract_intrinsic_value(metrics: Mapping[str, object]) -> float | None:
    intrinsic = _read_numeric(metrics.get("intrinsic_value"))
    if intrinsic is not None:
        return intrinsic
    details_raw = metrics.get("details")
    if isinstance(details_raw, Mapping):
        return _read_numeric(details_raw.get("intrinsic_value"))
    return None


def _extract_series_summary(
    params: Mapping[str, object] | None,
    *,
    field: str,
) -> JSONObject:
    if not isinstance(params, Mapping):
        return {"count": 0, "year1": None, "yearN": None}
    raw = params.get(field)
    if not isinstance(raw, list | tuple) or not raw:
        return {"count": 0, "year1": None, "yearN": None}
    values: list[float] = []
    for item in raw:
        number = _read_numeric(item)
        if number is None:
            return {"count": 0, "year1": None, "yearN": None}
        values.append(number)
    return {
        "count": len(values),
        "year1": values[0],
        "yearN": values[-1],
    }


def _extract_guardrail_from_assumptions(
    assumptions: list[str],
    *,
    kind: str,
) -> JSONObject | None:
    for assumption in assumptions:
        parsed = _GUARDRAIL_APPLIED_PATTERN.match(assumption)
        if parsed is None:
            continue
        if parsed.group("kind") != kind:
            continue
        reasons_raw = parsed.group("reasons").strip()
        reasons = [] if reasons_raw == "none" else reasons_raw.split("|")
        return {
            "applied": True,
            "version": parsed.group("version"),
            "profile": parsed.group("profile"),
            "raw_year1": float(parsed.group("raw_year1")),
            "raw_yearN": float(parsed.group("raw_yearN")),
            "guarded_year1": float(parsed.group("guarded_year1")),
            "guarded_yearN": float(parsed.group("guarded_yearN")),
            "reasons": reasons,
        }
    return None


def _extract_reinvestment_guardrail_from_assumptions(
    assumptions: list[str],
    *,
    metric: str,
) -> JSONObject | None:
    for assumption in assumptions:
        parsed = _REINVESTMENT_GUARDRAIL_APPLIED_PATTERN.match(assumption)
        if parsed is None:
            continue
        if parsed.group("metric") != metric:
            continue
        reasons_raw = parsed.group("reasons").strip()
        reasons = [] if reasons_raw == "none" else reasons_raw.split("|")
        anchor_raw = parsed.group("anchor").strip()
        try:
            anchor = float(anchor_raw)
        except ValueError:
            anchor = None
        return {
            "applied": True,
            "version": parsed.group("version"),
            "profile": parsed.group("profile"),
            "metric": parsed.group("metric"),
            "raw_year1": float(parsed.group("raw_year1")),
            "raw_yearN": float(parsed.group("raw_yearN")),
            "guarded_year1": float(parsed.group("guarded_year1")),
            "guarded_yearN": float(parsed.group("guarded_yearN")),
            "anchor": anchor,
            "anchor_samples": int(parsed.group("anchor_samples")),
            "reasons": reasons,
        }
    return None


def _extract_consensus_decay_window_years(assumptions: list[str]) -> int | None:
    for assumption in assumptions:
        matched = _CONSENSUS_DECAY_WINDOW_PATTERN.match(assumption)
        if matched is not None:
            return int(matched.group("window"))
    return None


def _extract_terminal_growth_fallback_mode(assumptions: list[str]) -> str | None:
    for assumption in assumptions:
        matched = _TERMINAL_GROWTH_FALLBACK_MODE_PATTERN.match(assumption)
        if matched is not None:
            return matched.group("mode")
    return None


def _extract_terminal_growth_anchor_source(assumptions: list[str]) -> str | None:
    for assumption in assumptions:
        matched = _TERMINAL_GROWTH_ANCHOR_SOURCE_PATTERN.match(assumption)
        if matched is not None:
            return matched.group("source")
    return None


def _extract_terminal_growth_path_from_metadata(
    metadata: Mapping[str, object] | None,
) -> tuple[str | None, str | None]:
    if not isinstance(metadata, Mapping):
        return None, None

    data_freshness_raw = metadata.get("data_freshness")
    if isinstance(data_freshness_raw, Mapping):
        path_raw = data_freshness_raw.get("terminal_growth_path")
        if isinstance(path_raw, Mapping):
            fallback_mode_raw = path_raw.get("terminal_growth_fallback_mode")
            anchor_source_raw = path_raw.get("terminal_growth_anchor_source")
            fallback_mode = (
                fallback_mode_raw
                if isinstance(fallback_mode_raw, str) and fallback_mode_raw
                else None
            )
            anchor_source = (
                anchor_source_raw
                if isinstance(anchor_source_raw, str) and anchor_source_raw
                else None
            )
            if fallback_mode is not None or anchor_source is not None:
                return fallback_mode, anchor_source

    parameter_source_raw = metadata.get("parameter_source_summary")
    if isinstance(parameter_source_raw, Mapping):
        path_raw = parameter_source_raw.get("terminal_growth_path")
        if isinstance(path_raw, Mapping):
            fallback_mode_raw = path_raw.get("terminal_growth_fallback_mode")
            anchor_source_raw = path_raw.get("terminal_growth_anchor_source")
            fallback_mode = (
                fallback_mode_raw
                if isinstance(fallback_mode_raw, str) and fallback_mode_raw
                else None
            )
            anchor_source = (
                anchor_source_raw
                if isinstance(anchor_source_raw, str) and anchor_source_raw
                else None
            )
            if fallback_mode is not None or anchor_source is not None:
                return fallback_mode, anchor_source
    return None, None


def _extract_target_consensus_quality_from_metadata(
    metadata: Mapping[str, object] | None,
) -> tuple[str | None, float | None]:
    if not isinstance(metadata, Mapping):
        return None, None

    data_freshness_raw = metadata.get("data_freshness")
    if not isinstance(data_freshness_raw, Mapping):
        return None, None
    market_data_raw = data_freshness_raw.get("market_data")
    if not isinstance(market_data_raw, Mapping):
        return None, None

    quality_bucket_raw = market_data_raw.get("target_consensus_quality_bucket")
    confidence_weight_raw = market_data_raw.get("target_consensus_confidence_weight")
    quality_bucket = (
        quality_bucket_raw
        if isinstance(quality_bucket_raw, str) and quality_bucket_raw
        else None
    )
    confidence_weight = (
        float(confidence_weight_raw)
        if isinstance(confidence_weight_raw, int | float)
        else None
    )
    return quality_bucket, confidence_weight


def _extract_target_consensus_warning_codes_from_metadata(
    metadata: Mapping[str, object] | None,
) -> list[str] | None:
    if not isinstance(metadata, Mapping):
        return None

    sources: list[Mapping[str, object]] = []
    data_freshness_raw = metadata.get("data_freshness")
    if isinstance(data_freshness_raw, Mapping):
        market_data_raw = data_freshness_raw.get("market_data")
        if isinstance(market_data_raw, Mapping):
            sources.append(market_data_raw)
    parameter_source_raw = metadata.get("parameter_source_summary")
    if isinstance(parameter_source_raw, Mapping):
        market_anchor_raw = parameter_source_raw.get("market_data_anchor")
        if isinstance(market_anchor_raw, Mapping):
            sources.append(market_anchor_raw)

    codes: list[str] = []
    for source in sources:
        raw_codes = source.get("target_consensus_warning_codes")
        if not isinstance(raw_codes, list):
            continue
        for item in raw_codes:
            if isinstance(item, str) and item:
                codes.append(item)
    if not codes:
        return None
    return list(dict.fromkeys(codes))


def _extract_shares_path_from_metadata(
    metadata: Mapping[str, object] | None,
) -> JSONObject | None:
    if not isinstance(metadata, Mapping):
        return None

    shares_path_raw: Mapping[str, object] | None = None
    data_freshness_raw = metadata.get("data_freshness")
    if isinstance(data_freshness_raw, Mapping):
        candidate = data_freshness_raw.get("shares_path")
        if isinstance(candidate, Mapping):
            shares_path_raw = candidate
    if shares_path_raw is None:
        parameter_source_raw = metadata.get("parameter_source_summary")
        if isinstance(parameter_source_raw, Mapping):
            shares_raw = parameter_source_raw.get("shares_outstanding")
            if isinstance(shares_raw, Mapping):
                shares_path_raw = shares_raw
    if shares_path_raw is None:
        return None

    output: JSONObject = {}
    for key in (
        "selected_source",
        "shares_scope",
        "equity_value_scope",
        "scope_policy_mode",
        "scope_policy_resolution",
    ):
        raw = shares_path_raw.get(key)
        if isinstance(raw, str) and raw:
            output[key] = raw
    for key in (
        "scope_mismatch_detected",
        "scope_mismatch_resolved",
    ):
        raw = shares_path_raw.get(key)
        if isinstance(raw, bool):
            output[key] = raw
    for key in (
        "scope_mismatch_ratio",
        "market_shares",
        "filing_shares",
        "selected_shares",
        "selected_shares_before_policy",
    ):
        raw = shares_path_raw.get(key)
        if isinstance(raw, int | float):
            output[key] = float(raw)
    return output or None


def _extract_forward_signal_bp(metadata: Mapping[str, object] | None) -> JSONObject:
    calibration_block: Mapping[str, object] | None = None
    if isinstance(metadata, Mapping):
        raw_calibration_block = metadata.get("forward_signal_calibration")
        if isinstance(raw_calibration_block, Mapping):
            calibration_block = raw_calibration_block

    calibration_degraded_reason: str | None = None
    if calibration_block is not None:
        degraded_reason_raw = calibration_block.get("degraded_reason")
        if isinstance(degraded_reason_raw, str) and degraded_reason_raw.strip():
            calibration_degraded_reason = degraded_reason_raw

    if not isinstance(metadata, Mapping):
        return {
            "growth_adjustment_basis_points": None,
            "margin_adjustment_basis_points": None,
            "raw_growth_adjustment_basis_points": None,
            "raw_margin_adjustment_basis_points": None,
            "calibration_applied": None,
            "mapping_version": None,
            "calibration_degraded_reason": calibration_degraded_reason,
        }
    forward_signal = metadata.get("forward_signal")
    if not isinstance(forward_signal, Mapping):
        return {
            "growth_adjustment_basis_points": None,
            "margin_adjustment_basis_points": None,
            "raw_growth_adjustment_basis_points": None,
            "raw_margin_adjustment_basis_points": None,
            "calibration_applied": None,
            "mapping_version": None,
            "calibration_degraded_reason": calibration_degraded_reason,
        }
    calibration_applied_raw = forward_signal.get("calibration_applied")
    if not isinstance(calibration_applied_raw, bool):
        raise ReplayContractError(
            "forward_signal.calibration_applied missing or invalid; "
            "legacy payload is not supported",
            error_code=ReplayErrorCode.LEGACY_PAYLOAD_NOT_SUPPORTED.value,
        )
    mapping_version_raw = forward_signal.get("mapping_version")
    if not isinstance(mapping_version_raw, str) or not mapping_version_raw.strip():
        raise ReplayContractError(
            "forward_signal.mapping_version missing or invalid; "
            "legacy payload is not supported",
            error_code=ReplayErrorCode.LEGACY_PAYLOAD_NOT_SUPPORTED.value,
        )
    return {
        "growth_adjustment_basis_points": _read_numeric(
            forward_signal.get("growth_adjustment_basis_points")
        ),
        "margin_adjustment_basis_points": _read_numeric(
            forward_signal.get("margin_adjustment_basis_points")
        ),
        "raw_growth_adjustment_basis_points": _read_numeric(
            forward_signal.get("raw_growth_adjustment_basis_points")
        ),
        "raw_margin_adjustment_basis_points": _read_numeric(
            forward_signal.get("raw_margin_adjustment_basis_points")
        ),
        "calibration_applied": calibration_applied_raw,
        "mapping_version": mapping_version_raw,
        "calibration_degraded_reason": calibration_degraded_reason,
    }


def _series_year_delta(
    baseline_summary: Mapping[str, object],
    replay_summary: Mapping[str, object],
    *,
    key: str,
) -> float | None:
    baseline = _read_numeric(baseline_summary.get(key))
    replayed = _read_numeric(replay_summary.get(key))
    if baseline is None or replayed is None:
        return None
    return replayed - baseline


def _merge_market_snapshot_forward_signals(
    *,
    replay_market_snapshot: Mapping[str, object] | None,
    forward_signals: list[dict[str, object]] | None,
    staleness_mode: str,
) -> JSONObject | None:
    if replay_market_snapshot is None and not isinstance(forward_signals, list):
        return None
    snapshot: JSONObject = {}
    if isinstance(replay_market_snapshot, Mapping):
        snapshot.update(dict(replay_market_snapshot))
    if isinstance(forward_signals, list):
        snapshot["forward_signals"] = list(forward_signals)
    if staleness_mode == "recompute":
        recomputed = _recompute_market_staleness(snapshot)
        if isinstance(recomputed, Mapping):
            snapshot = dict(recomputed)
    return snapshot


def _calculate_intrinsic_from_params_dump(
    *,
    model_type: str,
    params_dump: Mapping[str, object],
) -> float | None:
    model_runtime = parse_valuation_model_runtime(
        ValuationModelRegistry.get_model_runtime(model_type),
        context=f"replay valuation model runtime for {model_type}",
    )
    params_payload = dict(params_dump)
    # Remove trace payload so what-if replacements use explicit parameter values.
    params_payload.pop("trace_inputs", None)
    params_obj = model_runtime.schema(**params_payload)
    metrics = parse_calculation_metrics(
        model_runtime.calculator(params_obj),
        context=f"{model_type} replay valuation result (group_delta)",
    )
    return _extract_intrinsic_value(metrics)


def _build_delta_by_parameter_group(
    *,
    model_type: str,
    baseline_params: Mapping[str, object] | None,
    replay_params: Mapping[str, object],
    replay_intrinsic: float,
    baseline_intrinsic: float | None,
) -> JSONObject | None:
    if not isinstance(baseline_params, Mapping):
        return None
    payload: JSONObject = {
        "method": "one_at_a_time_revert_to_baseline",
        "total_intrinsic_delta_vs_baseline": (
            replay_intrinsic - baseline_intrinsic
            if baseline_intrinsic is not None
            else None
        ),
        "groups": {},
    }
    groups_raw = payload["groups"]
    if not isinstance(groups_raw, dict):
        return None
    groups: dict[str, object] = groups_raw

    for group, fields in _PARAMETER_GROUP_FIELDS.items():
        candidate_params = dict(replay_params)
        applied_fields: list[str] = []
        for field in fields:
            if field in baseline_params:
                candidate_params[field] = baseline_params[field]
                applied_fields.append(field)
            elif field in candidate_params:
                candidate_params.pop(field)

        if not applied_fields:
            groups[group] = {
                "status": "skipped",
                "fields": list(fields),
                "reason": "baseline_fields_missing",
            }
            continue

        try:
            reverted_intrinsic = _calculate_intrinsic_from_params_dump(
                model_type=model_type,
                params_dump=candidate_params,
            )
        except Exception as exc:  # noqa: BLE001
            groups[group] = {
                "status": "error",
                "fields": applied_fields,
                "error": str(exc),
            }
            continue
        if reverted_intrinsic is None:
            groups[group] = {
                "status": "error",
                "fields": applied_fields,
                "error": "intrinsic_value_missing",
            }
            continue
        groups[group] = {
            "status": "ok",
            "fields": applied_fields,
            "intrinsic_if_reverted_to_baseline": reverted_intrinsic,
            "delta_vs_replay": replay_intrinsic - reverted_intrinsic,
        }
    return payload


def _replay_valuation(
    *,
    replay_input: ValuationReplayInputModel,
) -> tuple[JSONObject, JSONObject, list[str], JSONObject]:
    model_type = replay_input.model_type
    ticker = replay_input.ticker

    reports_raw: list[JSONObject] = [
        report.model_dump(mode="json", exclude_none=False)
        for report in replay_input.reports
    ]
    canonical_reports = parse_financial_reports_model(
        reports_raw,
        context="replay.financial_reports",
        inject_default_provenance=True,
    )
    market_snapshot = _merge_market_snapshot_forward_signals(
        replay_market_snapshot=replay_input.market_snapshot,
        forward_signals=replay_input.forward_signals,
        staleness_mode=replay_input.staleness_mode,
    )
    build_result = build_params(
        model_type,
        ticker,
        canonical_reports,
        market_snapshot=market_snapshot,
    )
    if build_result.missing:
        raise ReplayContractError(
            "replay build_params missing inputs: " + ",".join(build_result.missing),
            error_code=ReplayErrorCode.PARAM_BUILD_MISSING_INPUTS.value,
        )

    model_runtime = parse_valuation_model_runtime(
        ValuationModelRegistry.get_model_runtime(model_type),
        context=f"replay valuation model runtime for {model_type}",
    )
    params_dict = dict(build_result.params)
    params_dict["trace_inputs"] = build_result.trace_inputs
    params_obj = model_runtime.schema(**params_dict)
    params_dump = params_obj.model_dump(mode="json")
    if not isinstance(params_dump, dict):
        raise ReplayContractError(
            "replay params_dump must serialize to object",
            error_code=ReplayErrorCode.REPLAY_OUTPUT_INVALID.value,
        )

    calculation_metrics = parse_calculation_metrics(
        model_runtime.calculator(params_obj),
        context=f"{model_type} replay valuation result",
    )
    replay_metadata = (
        dict(build_result.metadata)
        if isinstance(build_result.metadata, Mapping)
        else {}
    )
    return (
        params_dump,
        calculation_metrics,
        list(build_result.assumptions),
        replay_metadata,
    )


def _build_report(
    *,
    replay_input: ValuationReplayInputModel,
    replay_params_dump: Mapping[str, object],
    replay_calculation_metrics: Mapping[str, object],
    replay_assumptions: list[str],
    replay_metadata: Mapping[str, object],
    override_payload: Mapping[str, object],
    abs_tol: float,
    rel_tol: float,
) -> JSONObject:
    baseline = replay_input.baseline
    baseline_params = baseline.params_dump if baseline is not None else None
    baseline_metrics = baseline.calculation_metrics if baseline is not None else None
    baseline_assumptions = baseline.assumptions if baseline is not None else []
    baseline_build_metadata = baseline.build_metadata if baseline is not None else None
    baseline_diagnostics = baseline.diagnostics if baseline is not None else None

    baseline_intrinsic = (
        _extract_intrinsic_value(baseline_metrics)
        if isinstance(baseline_metrics, Mapping)
        else None
    )
    replay_intrinsic = _extract_intrinsic_value(replay_calculation_metrics)
    intrinsic_delta = (
        replay_intrinsic - baseline_intrinsic
        if replay_intrinsic is not None and baseline_intrinsic is not None
        else None
    )
    delta_by_parameter_group = (
        _build_delta_by_parameter_group(
            model_type=replay_input.model_type,
            baseline_params=baseline_params
            if isinstance(baseline_params, Mapping)
            else None,
            replay_params=replay_params_dump,
            replay_intrinsic=replay_intrinsic,
            baseline_intrinsic=baseline_intrinsic,
        )
        if replay_intrinsic is not None
        else None
    )

    baseline_wacc = (
        _read_numeric(baseline_params.get("wacc"))
        if isinstance(baseline_params, Mapping)
        else None
    )
    replay_wacc = _read_numeric(replay_params_dump.get("wacc"))
    baseline_terminal_growth = (
        _read_numeric(baseline_params.get("terminal_growth"))
        if isinstance(baseline_params, Mapping)
        else None
    )
    replay_terminal_growth = _read_numeric(replay_params_dump.get("terminal_growth"))

    baseline_growth_summary = _extract_series_summary(
        baseline_params,
        field="growth_rates",
    )
    replay_growth_summary = _extract_series_summary(
        replay_params_dump,
        field="growth_rates",
    )
    baseline_margin_summary = _extract_series_summary(
        baseline_params,
        field="operating_margins",
    )
    replay_margin_summary = _extract_series_summary(
        replay_params_dump,
        field="operating_margins",
    )
    baseline_capex_summary = _extract_series_summary(
        baseline_params,
        field="capex_rates",
    )
    replay_capex_summary = _extract_series_summary(
        replay_params_dump,
        field="capex_rates",
    )
    baseline_wc_summary = _extract_series_summary(
        baseline_params,
        field="wc_rates",
    )
    replay_wc_summary = _extract_series_summary(
        replay_params_dump,
        field="wc_rates",
    )

    baseline_forward_signal = _extract_forward_signal_bp(baseline_build_metadata)
    replay_forward_signal = _extract_forward_signal_bp(replay_metadata)

    replay_growth_guardrail = _extract_guardrail_from_assumptions(
        replay_assumptions,
        kind="growth",
    )
    replay_margin_guardrail = _extract_guardrail_from_assumptions(
        replay_assumptions,
        kind="margin",
    )
    baseline_capex_guardrail = _extract_reinvestment_guardrail_from_assumptions(
        baseline_assumptions,
        metric="capex_rates",
    )
    replay_capex_guardrail = _extract_reinvestment_guardrail_from_assumptions(
        replay_assumptions,
        metric="capex_rates",
    )
    baseline_wc_guardrail = _extract_reinvestment_guardrail_from_assumptions(
        baseline_assumptions,
        metric="wc_rates",
    )
    replay_wc_guardrail = _extract_reinvestment_guardrail_from_assumptions(
        replay_assumptions,
        metric="wc_rates",
    )
    replay_consensus_decay_window = _extract_consensus_decay_window_years(
        replay_assumptions
    )
    (
        baseline_terminal_growth_fallback_mode,
        baseline_terminal_growth_anchor_source,
    ) = _extract_terminal_growth_path_from_metadata(baseline_build_metadata)
    if baseline_terminal_growth_fallback_mode is None:
        baseline_terminal_growth_fallback_mode = _extract_terminal_growth_fallback_mode(
            baseline_assumptions
        )
    if baseline_terminal_growth_anchor_source is None:
        baseline_terminal_growth_anchor_source = _extract_terminal_growth_anchor_source(
            baseline_assumptions
        )
    (
        replay_terminal_growth_fallback_mode,
        replay_terminal_growth_anchor_source,
    ) = _extract_terminal_growth_path_from_metadata(replay_metadata)
    if replay_terminal_growth_fallback_mode is None:
        replay_terminal_growth_fallback_mode = _extract_terminal_growth_fallback_mode(
            replay_assumptions
        )
    if replay_terminal_growth_anchor_source is None:
        replay_terminal_growth_anchor_source = _extract_terminal_growth_anchor_source(
            replay_assumptions
        )
    baseline_shares_path = _extract_shares_path_from_metadata(baseline_build_metadata)
    replayed_shares_path = _extract_shares_path_from_metadata(replay_metadata)
    (
        baseline_target_consensus_quality_bucket,
        baseline_target_consensus_confidence_weight,
    ) = _extract_target_consensus_quality_from_metadata(baseline_build_metadata)
    (
        replayed_target_consensus_quality_bucket,
        replayed_target_consensus_confidence_weight,
    ) = _extract_target_consensus_quality_from_metadata(replay_metadata)
    baseline_target_consensus_warning_codes = (
        _extract_target_consensus_warning_codes_from_metadata(baseline_build_metadata)
    )
    replayed_target_consensus_warning_codes = (
        _extract_target_consensus_warning_codes_from_metadata(replay_metadata)
    )
    baseline_warning_code_set = set(
        baseline_target_consensus_warning_codes or [],
    )
    replayed_warning_code_set = set(
        replayed_target_consensus_warning_codes or [],
    )
    warning_codes_added = sorted(replayed_warning_code_set - baseline_warning_code_set)
    warning_codes_removed = sorted(
        baseline_warning_code_set - replayed_warning_code_set
    )

    intrinsic_within_tol: bool | None = None
    if replay_intrinsic is not None and baseline_intrinsic is not None:
        intrinsic_within_tol = _is_within_tolerance(
            actual=replay_intrinsic,
            expected=baseline_intrinsic,
            abs_tol=abs_tol,
            rel_tol=rel_tol,
        )

    report: JSONObject = {
        "input_schema_version": replay_input.schema_version,
        "model_type": replay_input.model_type,
        "ticker": replay_input.ticker,
        "replay_staleness_mode": replay_input.staleness_mode,
        "override_applied": bool(override_payload),
        "override_keys": sorted(
            key for key in override_payload.keys() if isinstance(key, str)
        ),
        "has_replay_market_snapshot": isinstance(replay_input.market_snapshot, Mapping),
        "baseline_available": isinstance(baseline_metrics, Mapping),
        "baseline_intrinsic_value": baseline_intrinsic,
        "replayed_intrinsic_value": replay_intrinsic,
        "intrinsic_delta": intrinsic_delta,
        "delta_by_parameter_group": delta_by_parameter_group,
        "intrinsic_within_tolerance": intrinsic_within_tol,
        "baseline_wacc": baseline_wacc,
        "replayed_wacc": replay_wacc,
        "baseline_terminal_growth": baseline_terminal_growth,
        "replayed_terminal_growth": replay_terminal_growth,
        "baseline_growth_rates_summary": baseline_growth_summary,
        "replayed_growth_rates_summary": replay_growth_summary,
        "baseline_operating_margins_summary": baseline_margin_summary,
        "replayed_operating_margins_summary": replay_margin_summary,
        "baseline_capex_rates_summary": baseline_capex_summary,
        "replayed_capex_rates_summary": replay_capex_summary,
        "baseline_wc_rates_summary": baseline_wc_summary,
        "replayed_wc_rates_summary": replay_wc_summary,
        "growth_year1_delta": _series_year_delta(
            baseline_growth_summary,
            replay_growth_summary,
            key="year1",
        ),
        "growth_yearN_delta": _series_year_delta(
            baseline_growth_summary,
            replay_growth_summary,
            key="yearN",
        ),
        "margin_year1_delta": _series_year_delta(
            baseline_margin_summary,
            replay_margin_summary,
            key="year1",
        ),
        "margin_yearN_delta": _series_year_delta(
            baseline_margin_summary,
            replay_margin_summary,
            key="yearN",
        ),
        "capex_year1_delta": _series_year_delta(
            baseline_capex_summary,
            replay_capex_summary,
            key="year1",
        ),
        "capex_yearN_delta": _series_year_delta(
            baseline_capex_summary,
            replay_capex_summary,
            key="yearN",
        ),
        "wc_year1_delta": _series_year_delta(
            baseline_wc_summary,
            replay_wc_summary,
            key="year1",
        ),
        "wc_yearN_delta": _series_year_delta(
            baseline_wc_summary,
            replay_wc_summary,
            key="yearN",
        ),
        "baseline_forward_signal": baseline_forward_signal,
        "replayed_forward_signal": replay_forward_signal,
        "forward_signal_growth_bp_delta": _series_year_delta(
            baseline_forward_signal,
            replay_forward_signal,
            key="growth_adjustment_basis_points",
        ),
        "forward_signal_margin_bp_delta": _series_year_delta(
            baseline_forward_signal,
            replay_forward_signal,
            key="margin_adjustment_basis_points",
        ),
        "baseline_assumptions_count": len(baseline_assumptions),
        "replayed_assumptions_count": len(replay_assumptions),
        "replayed_growth_guardrail": replay_growth_guardrail,
        "replayed_margin_guardrail": replay_margin_guardrail,
        "baseline_capex_guardrail": baseline_capex_guardrail,
        "replayed_capex_guardrail": replay_capex_guardrail,
        "baseline_wc_guardrail": baseline_wc_guardrail,
        "replayed_wc_guardrail": replay_wc_guardrail,
        "baseline_growth_consensus_window_years": (
            baseline_diagnostics.get("growth_consensus_window_years")
            if isinstance(baseline_diagnostics, Mapping)
            else None
        ),
        "replayed_growth_consensus_window_years": replay_consensus_decay_window,
        "baseline_terminal_growth_fallback_mode": baseline_terminal_growth_fallback_mode,
        "replayed_terminal_growth_fallback_mode": replay_terminal_growth_fallback_mode,
        "baseline_terminal_growth_anchor_source": baseline_terminal_growth_anchor_source,
        "replayed_terminal_growth_anchor_source": replay_terminal_growth_anchor_source,
        "baseline_target_consensus_quality_bucket": (
            baseline_target_consensus_quality_bucket
        ),
        "replayed_target_consensus_quality_bucket": (
            replayed_target_consensus_quality_bucket
        ),
        "baseline_target_consensus_confidence_weight": (
            baseline_target_consensus_confidence_weight
        ),
        "replayed_target_consensus_confidence_weight": (
            replayed_target_consensus_confidence_weight
        ),
        "baseline_target_consensus_warning_codes": (
            baseline_target_consensus_warning_codes
        ),
        "replayed_target_consensus_warning_codes": (
            replayed_target_consensus_warning_codes
        ),
        "baseline_target_consensus_warning_code_count": len(
            baseline_target_consensus_warning_codes or []
        ),
        "replayed_target_consensus_warning_code_count": len(
            replayed_target_consensus_warning_codes or []
        ),
        "target_consensus_warning_codes_added": warning_codes_added,
        "target_consensus_warning_codes_removed": warning_codes_removed,
        "baseline_shares_path": baseline_shares_path,
        "replayed_shares_path": replayed_shares_path,
    }
    return report


async def _run() -> int:
    args = parse_args()

    replay_input = _load_replay_input(args.input)
    cli_override = _load_override_input(args.override_json)
    override_payload = _effective_override_payload(
        replay_input,
        cli_override=cli_override,
    )
    replay_input = _apply_replay_override(
        replay_input,
        override_payload=override_payload,
    )
    (
        replay_params_dump,
        replay_calculation_metrics,
        replay_assumptions,
        replay_metadata,
    ) = _replay_valuation(
        replay_input=replay_input,
    )

    report = _build_report(
        replay_input=replay_input,
        replay_params_dump=replay_params_dump,
        replay_calculation_metrics=replay_calculation_metrics,
        replay_assumptions=replay_assumptions,
        replay_metadata=replay_metadata,
        override_payload=override_payload,
        abs_tol=args.abs_tol,
        rel_tol=args.rel_tol,
    )
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


def main() -> int:
    try:
        return asyncio.run(_run())
    except ReplayContractError as exc:
        error_payload = {
            "status": "error",
            "error_code": exc.error_code,
            "error": str(exc),
        }
        print(json.dumps(error_payload, ensure_ascii=False))
        return 1
    except Exception as exc:  # noqa: BLE001
        error_payload = {
            "status": "error",
            "error_code": ReplayErrorCode.REPLAY_RUNTIME_ERROR.value,
            "error": str(exc),
        }
        print(json.dumps(error_payload, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
