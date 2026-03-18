from __future__ import annotations

from src.agents.technical.application.semantic_pipeline_contracts import (
    TechnicalProjectionArtifacts,
)
from src.agents.technical.application.technical_evidence_bundle_service import (
    build_projection_context_from_evidence,
)
from src.shared.kernel.types import JSONObject


def build_report_projection_context(
    *,
    artifacts: TechnicalProjectionArtifacts,
) -> JSONObject:
    context = build_projection_context_from_evidence(artifacts.evidence_bundle)
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
