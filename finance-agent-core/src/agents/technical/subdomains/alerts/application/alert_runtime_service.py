from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from src.interface.artifacts.artifact_data_models import (
    TechnicalIndicatorSeriesArtifactData,
    TechnicalIndicatorSeriesFrameData,
    TechnicalPatternPackArtifactData,
)

ALERT_POLICY_VERSION = "1.0"


@dataclass(frozen=True)
class AlertEvidenceRef:
    artifact_kind: str
    artifact_id: str | None = None
    timeframe: str | None = None
    signal_key: str | None = None


@dataclass(frozen=True)
class AlertPolicyMetadata:
    policy_code: str
    policy_version: str
    lifecycle_state: str
    evidence_refs: tuple[AlertEvidenceRef, ...] = ()
    quality_gate: str | None = None
    trigger_reason: str | None = None
    suppression_reason: str | None = None


@dataclass(frozen=True)
class AlertSignal:
    code: str
    severity: str
    timeframe: str
    title: str
    message: str | None = None
    value: float | None = None
    threshold: float | None = None
    direction: str | None = None
    triggered_at: str | None = None
    source: str | None = None
    metadata: dict[str, object] | None = None
    policy: AlertPolicyMetadata | None = None


@dataclass(frozen=True)
class AlertSummary:
    total: int
    severity_counts: dict[str, int]
    generated_at: str
    policy_count: int
    lifecycle_counts: dict[str, int]
    quality_gate_counts: dict[str, int]


@dataclass(frozen=True)
class AlertRuntimeRequest:
    ticker: str
    as_of: str
    indicator_series: TechnicalIndicatorSeriesArtifactData | None
    pattern_pack: TechnicalPatternPackArtifactData | None


@dataclass(frozen=True)
class AlertRuntimeResult:
    ticker: str
    as_of: str
    alerts: list[AlertSignal]
    degraded_reasons: list[str]
    summary: AlertSummary


class AlertRuntimeService:
    def compute(self, request: AlertRuntimeRequest) -> AlertRuntimeResult:
        alerts: list[AlertSignal] = []
        degraded: list[str] = []

        if request.indicator_series is None:
            degraded.append("INDICATOR_SERIES_MISSING")
        else:
            alerts.extend(_build_threshold_alerts(request.indicator_series))

        if request.pattern_pack is None:
            degraded.append("PATTERN_PACK_MISSING")
        else:
            alerts.extend(_build_breakout_alerts(request.pattern_pack))

        if request.indicator_series is not None:
            alerts.extend(
                _build_rsi_support_rebound_alerts(
                    indicator_series=request.indicator_series,
                    pattern_pack=request.pattern_pack,
                )
            )

        summary = _build_summary(alerts)
        return AlertRuntimeResult(
            ticker=request.ticker,
            as_of=request.as_of,
            alerts=alerts,
            degraded_reasons=degraded,
            summary=summary,
        )


def _build_threshold_alerts(
    indicator_series: TechnicalIndicatorSeriesArtifactData,
) -> list[AlertSignal]:
    alerts: list[AlertSignal] = []
    for timeframe, frame in indicator_series.timeframes.items():
        rsi_alert = _rsi_alert(
            frame.series.get("RSI_14", {}),
            timeframe,
            frame=frame,
            artifact_id=None,
        )
        if rsi_alert:
            alerts.append(rsi_alert)

        fd_alerts = _fd_alerts(
            frame.series.get("FD_ZSCORE", {}),
            timeframe,
            frame=frame,
            artifact_id=None,
        )
        alerts.extend(fd_alerts)
    return alerts


def _rsi_alert(
    series: dict[str, float | None],
    timeframe: str,
    *,
    frame: TechnicalIndicatorSeriesFrameData,
    artifact_id: str | None,
) -> AlertSignal | None:
    timestamp, value = _latest_value(series)
    if value is None:
        return None

    quality_gate = _indicator_quality_gate(frame)
    evidence_refs = (
        AlertEvidenceRef(
            artifact_kind="ta_indicator_series",
            artifact_id=artifact_id,
            timeframe=timeframe,
            signal_key="RSI_14",
        ),
    )
    if value >= 70:
        severity = "critical" if value >= 80 else "warning"
        return AlertSignal(
            code="RSI_OVERBOUGHT",
            severity=severity,
            timeframe=timeframe,
            title="RSI Overbought",
            message="RSI is above the overbought threshold.",
            value=value,
            threshold=70,
            direction="above",
            triggered_at=timestamp,
            source="indicator_series",
            policy=AlertPolicyMetadata(
                policy_code="TA_RSI_14_EXTREME",
                policy_version=ALERT_POLICY_VERSION,
                lifecycle_state="active",
                evidence_refs=evidence_refs,
                quality_gate=quality_gate,
                trigger_reason=f"RSI_14 >= 70 (actual={value:.2f})",
            ),
        )
    if value <= 30:
        severity = "critical" if value <= 20 else "warning"
        return AlertSignal(
            code="RSI_OVERSOLD",
            severity=severity,
            timeframe=timeframe,
            title="RSI Oversold",
            message="RSI is below the oversold threshold.",
            value=value,
            threshold=30,
            direction="below",
            triggered_at=timestamp,
            source="indicator_series",
            policy=AlertPolicyMetadata(
                policy_code="TA_RSI_14_EXTREME",
                policy_version=ALERT_POLICY_VERSION,
                lifecycle_state="active",
                evidence_refs=evidence_refs,
                quality_gate=quality_gate,
                trigger_reason=f"RSI_14 <= 30 (actual={value:.2f})",
            ),
        )
    return None


def _fd_alerts(
    series: dict[str, float | None],
    timeframe: str,
    *,
    frame: TechnicalIndicatorSeriesFrameData,
    artifact_id: str | None,
) -> list[AlertSignal]:
    alerts: list[AlertSignal] = []
    timestamp, value = _latest_value(series)
    if value is None:
        return alerts
    quality_gate = _indicator_quality_gate(frame)
    evidence_refs = (
        AlertEvidenceRef(
            artifact_kind="ta_indicator_series",
            artifact_id=artifact_id,
            timeframe=timeframe,
            signal_key="FD_ZSCORE",
        ),
    )
    if value >= 2:
        alerts.append(
            AlertSignal(
                code="FD_ZSCORE_HIGH",
                severity="critical",
                timeframe=timeframe,
                title="FracDiff Z-Score High",
                message="FracDiff Z-Score breached the upper threshold.",
                value=value,
                threshold=2,
                direction="above",
                triggered_at=timestamp,
                source="indicator_series",
                policy=AlertPolicyMetadata(
                    policy_code="TA_FD_ZSCORE_EXTREME",
                    policy_version=ALERT_POLICY_VERSION,
                    lifecycle_state="active",
                    evidence_refs=evidence_refs,
                    quality_gate=quality_gate,
                    trigger_reason=f"FD_ZSCORE >= 2 (actual={value:.2f})",
                ),
            )
        )
    if value <= -2:
        alerts.append(
            AlertSignal(
                code="FD_ZSCORE_LOW",
                severity="critical",
                timeframe=timeframe,
                title="FracDiff Z-Score Low",
                message="FracDiff Z-Score breached the lower threshold.",
                value=value,
                threshold=-2,
                direction="below",
                triggered_at=timestamp,
                source="indicator_series",
                policy=AlertPolicyMetadata(
                    policy_code="TA_FD_ZSCORE_EXTREME",
                    policy_version=ALERT_POLICY_VERSION,
                    lifecycle_state="active",
                    evidence_refs=evidence_refs,
                    quality_gate=quality_gate,
                    trigger_reason=f"FD_ZSCORE <= -2 (actual={value:.2f})",
                ),
            )
        )
    return alerts


def _build_breakout_alerts(
    pattern_pack: TechnicalPatternPackArtifactData,
) -> list[AlertSignal]:
    alerts: list[AlertSignal] = []
    quality_gate = "degraded" if pattern_pack.degraded_reasons else "pass"
    for timeframe, frame in pattern_pack.timeframes.items():
        for breakout in frame.breakouts:
            confidence = breakout.confidence or 0.0
            severity = (
                "critical"
                if confidence >= 0.8
                else "warning"
                if confidence >= 0.6
                else "info"
            )
            alerts.append(
                AlertSignal(
                    code="BREAKOUT",
                    severity=severity,
                    timeframe=timeframe,
                    title=f"Breakout: {breakout.name}",
                    message=breakout.notes,
                    value=confidence,
                    threshold=None,
                    direction=None,
                    triggered_at=pattern_pack.as_of,
                    source="pattern_pack",
                    metadata={"confidence": confidence},
                    policy=AlertPolicyMetadata(
                        policy_code="TA_BREAKOUT_CONFIDENCE",
                        policy_version=ALERT_POLICY_VERSION,
                        lifecycle_state="active",
                        evidence_refs=(
                            AlertEvidenceRef(
                                artifact_kind="ta_pattern_pack",
                                artifact_id=None,
                                timeframe=timeframe,
                                signal_key=breakout.name,
                            ),
                        ),
                        quality_gate=quality_gate,
                        trigger_reason=(
                            f"{breakout.name} breakout confidence >= 0.60 "
                            f"(actual={confidence:.2f})"
                        ),
                    ),
                )
            )
    return alerts


def _build_rsi_support_rebound_alerts(
    *,
    indicator_series: TechnicalIndicatorSeriesArtifactData,
    pattern_pack: TechnicalPatternPackArtifactData | None,
) -> list[AlertSignal]:
    alerts: list[AlertSignal] = []
    for timeframe, frame in indicator_series.timeframes.items():
        timestamp, rsi_value = _latest_value(frame.series.get("RSI_14", {}))
        if rsi_value is None or rsi_value > 30:
            continue

        pattern_frame = (
            pattern_pack.timeframes.get(timeframe)
            if pattern_pack is not None and timeframe in pattern_pack.timeframes
            else None
        )
        pattern_quality_gate = (
            "degraded"
            if pattern_pack is None or pattern_pack.degraded_reasons
            else "pass"
        )
        quality_gate = _combine_quality_gates(
            _indicator_quality_gate(frame),
            pattern_quality_gate,
        )
        evidence_refs = [
            AlertEvidenceRef(
                artifact_kind="ta_indicator_series",
                artifact_id=None,
                timeframe=timeframe,
                signal_key="RSI_14",
            )
        ]
        if pattern_frame is not None:
            evidence_refs.append(
                AlertEvidenceRef(
                    artifact_kind="ta_pattern_pack",
                    artifact_id=None,
                    timeframe=timeframe,
                    signal_key="SUPPORT_CONTEXT",
                )
            )

        lifecycle_state = "suppressed"
        severity = "info"
        title = "RSI Oversold Rebound Setup"
        message = "Oversold signal lacks confirmed structural support."
        trigger_reason = (
            f"RSI_14 <= 30 (actual={rsi_value:.2f}) but rebound context is incomplete"
        )
        suppression_reason = "PATTERN_CONTEXT_MISSING"

        if pattern_frame is not None:
            support_confirmed = pattern_frame.confluence_metadata is not None and (
                pattern_frame.confluence_metadata.near_support is True
            )
            support_present = bool(pattern_frame.support_levels)
            nearest_support = (
                pattern_frame.confluence_metadata.nearest_support
                if pattern_frame.confluence_metadata is not None
                else None
            )

            if support_confirmed:
                lifecycle_state = "active"
                severity = "critical" if rsi_value <= 20 else "warning"
                title = "RSI Oversold Near Support"
                message = "Oversold pressure is aligning with nearby support."
                if nearest_support is not None:
                    message = (
                        "Oversold pressure is aligning with nearby support "
                        f"around {nearest_support:.2f}."
                    )
                trigger_reason = (
                    f"RSI_14 <= 30 (actual={rsi_value:.2f}) and support proximity "
                    "is confirmed"
                )
                suppression_reason = None
            elif support_present:
                lifecycle_state = "monitoring"
                severity = "info"
                title = "RSI Oversold Rebound Watch"
                message = (
                    "Oversold signal is present and support exists, but proximity is "
                    "not yet confirmed."
                )
                trigger_reason = (
                    f"RSI_14 <= 30 (actual={rsi_value:.2f}) with support levels present"
                )
                suppression_reason = "NEAR_SUPPORT_NOT_CONFIRMED"
            else:
                suppression_reason = "SUPPORT_LEVELS_UNAVAILABLE"

        alerts.append(
            AlertSignal(
                code="RSI_SUPPORT_REBOUND_SETUP",
                severity=severity,
                timeframe=timeframe,
                title=title,
                message=message,
                value=rsi_value,
                threshold=30,
                direction="below",
                triggered_at=timestamp,
                source="policy_alert",
                policy=AlertPolicyMetadata(
                    policy_code="TA_RSI_SUPPORT_REBOUND",
                    policy_version=ALERT_POLICY_VERSION,
                    lifecycle_state=lifecycle_state,
                    evidence_refs=tuple(evidence_refs),
                    quality_gate=quality_gate,
                    trigger_reason=trigger_reason,
                    suppression_reason=suppression_reason,
                ),
            )
        )
    return alerts


def _latest_value(
    series: dict[str, float | None],
) -> tuple[str | None, float | None]:
    if not series:
        return None, None
    for timestamp in sorted(series.keys(), reverse=True):
        value = series.get(timestamp)
        if value is None:
            continue
        try:
            value_num = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value_num):
            continue
        return timestamp, value_num
    return None, None


def _build_summary(alerts: list[AlertSignal]) -> AlertSummary:
    severity_counts = {"critical": 0, "warning": 0, "info": 0}
    lifecycle_counts: dict[str, int] = {}
    quality_gate_counts: dict[str, int] = {}
    policy_codes: set[str] = set()
    for alert in alerts:
        if alert.severity in severity_counts:
            severity_counts[alert.severity] += 1
        if alert.policy is not None:
            policy_codes.add(alert.policy.policy_code)
            lifecycle_counts[alert.policy.lifecycle_state] = (
                lifecycle_counts.get(alert.policy.lifecycle_state, 0) + 1
            )
            quality_gate = alert.policy.quality_gate or "unknown"
            quality_gate_counts[quality_gate] = (
                quality_gate_counts.get(quality_gate, 0) + 1
            )
    return AlertSummary(
        total=len(alerts),
        severity_counts=severity_counts,
        generated_at=datetime.now().isoformat(),
        policy_count=len(policy_codes),
        lifecycle_counts=lifecycle_counts,
        quality_gate_counts=quality_gate_counts,
    )


def _indicator_quality_gate(frame: TechnicalIndicatorSeriesFrameData) -> str:
    metadata = frame.metadata
    if metadata is None:
        return "pass"
    readiness = (metadata.sample_readiness or "").casefold()
    quality_flags = metadata.quality_flags or []
    if readiness not in {"", "ready"}:
        return "degraded"
    if quality_flags:
        return "degraded"
    return "pass"


def _combine_quality_gates(*gates: str) -> str:
    return "degraded" if any(gate == "degraded" for gate in gates) else "pass"
