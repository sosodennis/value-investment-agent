from __future__ import annotations

from src.agents.technical.application.semantic_pipeline_contracts import (
    TechnicalProjectionArtifacts,
)
from src.agents.technical.interface.evidence_bundle_projection_service import (
    build_projection_context_from_evidence,
)
from src.shared.kernel.types import JSONObject


def build_report_projection_context(
    *,
    artifacts: TechnicalProjectionArtifacts,
) -> JSONObject:
    context = build_projection_context_from_evidence(artifacts.evidence_bundle)
    signal_strength_summary = _build_signal_strength_summary(artifacts=artifacts)
    if signal_strength_summary is not None:
        context["signal_strength_summary"] = signal_strength_summary
    setup_reliability_summary = _build_setup_reliability_summary(artifacts=artifacts)
    if setup_reliability_summary is not None:
        context["setup_reliability_summary"] = setup_reliability_summary
    quality_summary = _build_quality_summary(artifacts=artifacts)
    if quality_summary is not None:
        context["quality_summary"] = quality_summary
    alert_readout = _build_alert_readout(artifacts=artifacts)
    if alert_readout is not None:
        context["alert_readout"] = alert_readout
    observability_summary = _build_observability_summary(artifacts=artifacts)
    if observability_summary is not None:
        context["observability_summary"] = observability_summary
    return context


def _build_signal_strength_summary(
    *,
    artifacts: TechnicalProjectionArtifacts,
) -> JSONObject | None:
    fusion_report = artifacts.fusion_report
    if fusion_report is None:
        return None
    raw_value = fusion_report.signal_strength_raw
    if raw_value is None:
        raw_value = fusion_report.confidence_raw
    effective_value = fusion_report.signal_strength_effective
    if effective_value is None:
        effective_value = raw_value
    display_value = effective_value if effective_value is not None else raw_value
    calibration_applied = (
        fusion_report.confidence_calibration.calibration_applied
        if fusion_report.confidence_calibration is not None
        else None
    )
    probability_eligible = (
        fusion_report.confidence_eligibility.eligible
        if fusion_report.confidence_eligibility is not None
        else None
    )
    if (
        raw_value is None
        and effective_value is None
        and calibration_applied is None
        and probability_eligible is None
    ):
        return None
    return {
        "raw_value": raw_value,
        "effective_value": effective_value,
        "display_percent": round(display_value * 100.0, 1)
        if isinstance(display_value, int | float)
        else None,
        "strength_level": _resolve_strength_level(display_value),
        "calibration_status": _resolve_calibration_status(
            calibration_applied=calibration_applied,
            probability_eligible=probability_eligible,
        ),
        "source": "fusion_runtime",
        "probability_eligible": probability_eligible,
    }


def _build_setup_reliability_summary(
    *,
    artifacts: TechnicalProjectionArtifacts,
) -> JSONObject | None:
    fusion_report = artifacts.fusion_report
    feature_pack = artifacts.feature_pack
    if fusion_report is None and feature_pack is None:
        return None

    degraded_reasons = _merge_unique(
        list(feature_pack.degraded_reasons or []) if feature_pack is not None else [],
        list(fusion_report.degraded_reasons or []) if fusion_report is not None else [],
        list(artifacts.alerts.degraded_reasons or [])
        if artifacts.alerts is not None
        else [],
    )
    conflict_reasons = (
        list(fusion_report.conflict_reasons or []) if fusion_report else []
    )
    calibration_applied = (
        fusion_report.confidence_calibration.calibration_applied
        if fusion_report is not None
        and fusion_report.confidence_calibration is not None
        else None
    )
    critical_artifact_missing = any(
        artifact is None
        for artifact in (
            artifacts.feature_pack,
            artifacts.pattern_pack,
            artifacts.regime_pack,
            artifacts.fusion_report,
        )
    )
    optional_artifact_missing = any(
        artifact is None
        for artifact in (artifacts.alerts, artifacts.direction_scorecard)
    )
    coverage_status = _resolve_coverage_status(
        critical_artifact_missing=critical_artifact_missing,
        optional_artifact_missing=optional_artifact_missing,
        degraded_reasons=degraded_reasons,
    )
    conflict_level = _resolve_conflict_level(conflict_reasons)
    reasons: list[str] = []
    if calibration_applied is not True:
        reasons.append("UNCALIBRATED")
    if degraded_reasons:
        reasons.append("DEGRADED_INPUTS")
    if conflict_reasons:
        reasons.append("CONFLICT_PRESENT")
    if coverage_status == "partial":
        reasons.append("PARTIAL_COVERAGE")
    if coverage_status == "limited":
        reasons.append("LIMITED_COVERAGE")
    level = _resolve_reliability_level(
        calibration_applied=calibration_applied,
        coverage_status=coverage_status,
        degraded_reason_count=len(degraded_reasons),
        conflict_count=len(conflict_reasons),
    )
    return {
        "level": level,
        "calibration_status": _resolve_calibration_status(
            calibration_applied=calibration_applied,
            probability_eligible=(
                fusion_report.confidence_eligibility.eligible
                if fusion_report is not None
                and fusion_report.confidence_eligibility is not None
                else None
            ),
        ),
        "coverage_status": coverage_status,
        "conflict_level": conflict_level,
        "reasons": reasons,
        "recommended_reliance": _resolve_recommended_reliance(level),
    }


def _build_quality_summary(
    *,
    artifacts: TechnicalProjectionArtifacts,
) -> JSONObject | None:
    feature_summary = (
        artifacts.feature_pack.feature_summary
        if artifacts.feature_pack is not None
        else None
    )
    alerts_summary = artifacts.alerts.summary if artifacts.alerts is not None else None
    degraded_reasons = _merge_unique(
        list(artifacts.feature_pack.degraded_reasons or [])
        if artifacts.feature_pack is not None
        else [],
        list(artifacts.fusion_report.degraded_reasons or [])
        if artifacts.fusion_report is not None
        else [],
        list(artifacts.alerts.degraded_reasons or [])
        if artifacts.alerts is not None
        else [],
    )
    if (
        feature_summary is None
        and alerts_summary is None
        and not degraded_reasons
        and artifacts.evidence_bundle is None
    ):
        return None

    payload: JSONObject = {
        "is_degraded": bool(degraded_reasons),
        "degraded_reasons": degraded_reasons,
    }
    if feature_summary is not None:
        payload["overall_quality"] = feature_summary.overall_quality
        payload["ready_timeframes"] = list(feature_summary.ready_timeframes or [])
        payload["degraded_timeframes"] = list(feature_summary.degraded_timeframes or [])
        payload["regime_inputs_ready_timeframes"] = list(
            feature_summary.regime_inputs_ready_timeframes or []
        )
        payload["unavailable_indicator_count"] = (
            feature_summary.unavailable_indicator_count
        )
    if alerts_summary is not None:
        payload["alert_quality_gate_counts"] = dict(
            alerts_summary.quality_gate_counts or {}
        )
    if artifacts.evidence_bundle is not None:
        payload["primary_timeframe"] = artifacts.evidence_bundle.primary_timeframe
    return payload


def _build_alert_readout(
    *,
    artifacts: TechnicalProjectionArtifacts,
) -> JSONObject | None:
    alerts_artifact = artifacts.alerts
    if alerts_artifact is None:
        return None
    summary = alerts_artifact.summary
    alerts = alerts_artifact.alerts
    if summary is None and not alerts:
        return None

    top_alerts: list[JSONObject] = []
    for alert in sorted(alerts, key=_alert_rank, reverse=True)[:3]:
        item: JSONObject = {
            "code": alert.code,
            "title": alert.title,
            "severity": alert.severity,
            "timeframe": alert.timeframe,
        }
        if alert.policy is not None:
            item["policy_code"] = alert.policy.policy_code
            item["lifecycle_state"] = alert.policy.lifecycle_state
        top_alerts.append(item)

    payload: JSONObject = {
        "total_alerts": summary.total if summary is not None else len(alerts),
        "policy_count": summary.policy_count if summary is not None else None,
        "highest_severity": _highest_severity(alerts),
        "active_alert_count": _lifecycle_count(alerts, "active"),
        "monitoring_alert_count": _lifecycle_count(alerts, "monitoring"),
        "suppressed_alert_count": _lifecycle_count(alerts, "suppressed"),
        "top_alerts": top_alerts,
    }
    if summary is not None and summary.quality_gate_counts is not None:
        payload["quality_gate_counts"] = dict(summary.quality_gate_counts)
    return payload


def _build_observability_summary(
    *,
    artifacts: TechnicalProjectionArtifacts,
) -> JSONObject | None:
    artifact_groups = {
        "feature_pack": artifacts.feature_pack,
        "pattern_pack": artifacts.pattern_pack,
        "regime_pack": artifacts.regime_pack,
        "fusion_report": artifacts.fusion_report,
        "alerts": artifacts.alerts,
        "direction_scorecard": artifacts.direction_scorecard,
    }
    loaded_artifacts = [
        name for name, artifact in artifact_groups.items() if artifact is not None
    ]
    missing_artifacts = [
        name for name, artifact in artifact_groups.items() if artifact is None
    ]
    degraded_artifacts = [
        name
        for name, artifact in artifact_groups.items()
        if artifact is not None
        and list(getattr(artifact, "degraded_reasons", []) or [])
    ]
    observed_timeframes = _merge_unique(
        _read_timeframes(getattr(artifacts.feature_pack, "timeframes", None)),
        _read_timeframes(getattr(artifacts.pattern_pack, "timeframes", None)),
        _read_timeframes(getattr(artifacts.regime_pack, "timeframes", None)),
    )
    primary_timeframe = (
        artifacts.evidence_bundle.primary_timeframe
        if artifacts.evidence_bundle is not None
        else None
    )
    degraded_reason_count = len(
        _merge_unique(
            list(getattr(artifacts.feature_pack, "degraded_reasons", []) or []),
            list(getattr(artifacts.pattern_pack, "degraded_reasons", []) or []),
            list(getattr(artifacts.regime_pack, "degraded_reasons", []) or []),
            list(getattr(artifacts.fusion_report, "degraded_reasons", []) or []),
            list(getattr(artifacts.alerts, "degraded_reasons", []) or []),
        )
    )
    if (
        not loaded_artifacts
        and not missing_artifacts
        and not observed_timeframes
        and primary_timeframe is None
    ):
        return None
    return {
        "primary_timeframe": primary_timeframe,
        "observed_timeframes": observed_timeframes,
        "loaded_artifacts": loaded_artifacts,
        "missing_artifacts": missing_artifacts,
        "degraded_artifacts": degraded_artifacts,
        "loaded_artifact_count": len(loaded_artifacts),
        "missing_artifact_count": len(missing_artifacts),
        "degraded_reason_count": degraded_reason_count,
    }


def _merge_unique(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for value in group:
            if value not in merged:
                merged.append(value)
    return merged


def _read_timeframes(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [key for key in value if isinstance(key, str)]


def _alert_rank(alert: object) -> tuple[int, int]:
    severity = getattr(alert, "severity", None)
    lifecycle = getattr(getattr(alert, "policy", None), "lifecycle_state", None)
    severity_rank = {"critical": 3, "warning": 2, "info": 1}.get(str(severity), 0)
    lifecycle_rank = {"active": 3, "monitoring": 2, "suppressed": 1}.get(
        str(lifecycle), 0
    )
    return severity_rank, lifecycle_rank


def _highest_severity(alerts: list[object]) -> str | None:
    if not alerts:
        return None
    ranked = max(alerts, key=_alert_rank)
    severity = getattr(ranked, "severity", None)
    return str(severity) if isinstance(severity, str) else None


def _lifecycle_count(alerts: list[object], state: str) -> int:
    total = 0
    for alert in alerts:
        lifecycle_state = getattr(
            getattr(alert, "policy", None), "lifecycle_state", None
        )
        if lifecycle_state == state:
            total += 1
    return total


def _resolve_strength_level(value: float | None) -> str | None:
    if value is None:
        return None
    if value >= 0.85:
        return "very_strong"
    if value >= 0.65:
        return "strong"
    if value >= 0.45:
        return "moderate"
    return "weak"


def _resolve_calibration_status(
    *,
    calibration_applied: bool | None,
    probability_eligible: bool | None,
) -> str:
    if calibration_applied is True:
        return "calibrated"
    if probability_eligible is False:
        return "ineligible"
    return "uncalibrated"


def _resolve_coverage_status(
    *,
    critical_artifact_missing: bool,
    optional_artifact_missing: bool,
    degraded_reasons: list[str],
) -> str:
    if critical_artifact_missing:
        return "limited"
    if degraded_reasons or optional_artifact_missing:
        return "partial"
    return "full"


def _resolve_conflict_level(conflict_reasons: list[str]) -> str:
    if not conflict_reasons:
        return "none"
    if len(conflict_reasons) == 1:
        return "present"
    return "elevated"


def _resolve_reliability_level(
    *,
    calibration_applied: bool | None,
    coverage_status: str,
    degraded_reason_count: int,
    conflict_count: int,
) -> str:
    if (
        calibration_applied is True
        and coverage_status == "full"
        and degraded_reason_count == 0
        and conflict_count == 0
    ):
        return "high"
    if (
        coverage_status == "limited"
        or degraded_reason_count >= 2
        or conflict_count >= 2
        or (calibration_applied is not True and degraded_reason_count > 0)
    ):
        return "low"
    return "medium"


def _resolve_recommended_reliance(level: str) -> str:
    return {
        "high": "primary",
        "medium": "supporting",
        "low": "cautious",
    }.get(level, "supporting")
