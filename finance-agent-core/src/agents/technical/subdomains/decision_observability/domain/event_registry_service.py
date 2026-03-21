from __future__ import annotations

import uuid
from datetime import UTC, datetime

from src.agents.technical.subdomains.decision_observability.domain.contracts import (
    TechnicalPredictionEventRecord,
)
from src.shared.kernel.types import JSONObject, JSONValue

_AGENT_SOURCE = "technical"
_DEFAULT_HORIZON = "5d"
_DEFAULT_TIMEFRAME = "1d"
_LOGIC_VERSION = "technical_decision_registry.v1"
_ALLOWED_HORIZONS = frozenset({"1d", "5d", "20d"})


def build_prediction_event_record(
    *,
    ticker: str,
    technical_context: JSONObject,
    full_report_payload: JSONObject,
    report_artifact_id: str,
    run_type: str,
) -> TechnicalPredictionEventRecord:
    horizon = _resolve_horizon(
        technical_context=technical_context,
        full_report_payload=full_report_payload,
    )
    timeframe = _resolve_timeframe(
        technical_context=technical_context,
        full_report_payload=full_report_payload,
    )
    direction = _resolve_direction(full_report_payload)
    raw_score = _resolve_numeric_field(
        technical_context,
        (
            "signal_strength_raw",
            "confidence_raw",
            "confidence_calibrated",
            "confidence",
        ),
    )
    confidence = _resolve_numeric_field(
        technical_context,
        ("confidence_calibrated", "confidence", "confidence_raw"),
    )
    artifact_refs = _coerce_object(full_report_payload.get("artifact_refs"))
    feature_contract_version = f"technical_artifact_schema:{full_report_payload.get('schema_version', 'unknown')}"

    return TechnicalPredictionEventRecord(
        event_id=str(uuid.uuid4()),
        agent_source=_AGENT_SOURCE,
        event_time=datetime.now(UTC).replace(tzinfo=None),
        ticker=ticker,
        timeframe=timeframe,
        horizon=horizon,
        direction=direction,
        raw_score=raw_score,
        confidence=confidence,
        reliability_level=_resolve_reliability_level(technical_context),
        logic_version=_LOGIC_VERSION,
        feature_contract_version=feature_contract_version,
        run_type=run_type,
        full_report_artifact_id=report_artifact_id,
        source_artifact_refs=artifact_refs,
        context_payload=_build_context_payload(
            technical_context=technical_context,
            full_report_payload=full_report_payload,
        ),
    )


def _resolve_horizon(
    *,
    technical_context: JSONObject,
    full_report_payload: JSONObject,
) -> str:
    candidate = technical_context.get("target_horizon")
    if not isinstance(candidate, str):
        candidate = technical_context.get("horizon")
    if not isinstance(candidate, str):
        candidate = full_report_payload.get("target_horizon")
    if not isinstance(candidate, str) or candidate not in _ALLOWED_HORIZONS:
        return _DEFAULT_HORIZON
    return candidate


def _resolve_timeframe(
    *,
    technical_context: JSONObject,
    full_report_payload: JSONObject,
) -> str:
    evidence_bundle = _coerce_object(full_report_payload.get("evidence_bundle"))
    primary_timeframe = evidence_bundle.get("primary_timeframe")
    if isinstance(primary_timeframe, str) and primary_timeframe:
        return primary_timeframe
    technical_timeframe = technical_context.get("primary_timeframe")
    if isinstance(technical_timeframe, str) and technical_timeframe:
        return technical_timeframe
    return _DEFAULT_TIMEFRAME


def _resolve_direction(full_report_payload: JSONObject) -> str:
    direction = full_report_payload.get("direction")
    if isinstance(direction, str) and direction:
        return direction
    raise ValueError("technical decision observability requires a report direction")


def _resolve_numeric_field(payload: JSONObject, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None


def _resolve_reliability_level(technical_context: JSONObject) -> str | None:
    summary = _coerce_object(technical_context.get("setup_reliability_summary"))
    level = summary.get("level")
    if isinstance(level, str) and level:
        return level
    return None


def _build_context_payload(
    *,
    technical_context: JSONObject,
    full_report_payload: JSONObject,
) -> JSONObject:
    evidence_bundle = _coerce_object(full_report_payload.get("evidence_bundle"))
    return {
        "as_of": _coerce_json_scalar(full_report_payload.get("as_of")),
        "summary_tags": _coerce_string_list(full_report_payload.get("summary_tags")),
        "setup_reliability_summary": _coerce_object(
            technical_context.get("setup_reliability_summary")
        ),
        "quality_summary": _coerce_object(technical_context.get("quality_summary")),
        "observability_summary": _coerce_object(
            technical_context.get("observability_summary")
        ),
        "signal_strength_summary": _coerce_object(
            technical_context.get("signal_strength_summary")
        ),
        "evidence_bundle": {
            "primary_timeframe": _coerce_json_scalar(
                evidence_bundle.get("primary_timeframe")
            ),
            "support_levels": _coerce_float_list(evidence_bundle.get("support_levels")),
            "resistance_levels": _coerce_float_list(
                evidence_bundle.get("resistance_levels")
            ),
            "conflict_reasons": _coerce_string_list(
                evidence_bundle.get("conflict_reasons")
            ),
        },
    }


def _coerce_object(raw: object) -> JSONObject:
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items() if _is_json_value(value)}
    return {}


def _coerce_string_list(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, str)]
    if isinstance(raw, tuple):
        return [item for item in raw if isinstance(item, str)]
    return []


def _coerce_float_list(raw: object) -> list[float]:
    values: list[float] = []
    if isinstance(raw, list | tuple):
        for item in raw:
            if isinstance(item, int | float):
                values.append(float(item))
    return values


def _coerce_json_scalar(raw: object) -> JSONValue:
    if isinstance(raw, str | int | float | bool) or raw is None:
        return raw
    return None


def _is_json_value(value: object) -> bool:
    if isinstance(value, str | int | float | bool) or value is None:
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _is_json_value(item) for key, item in value.items()
        )
    return False
