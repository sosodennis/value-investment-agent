from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

from src.interface.artifacts.artifact_data_models import (
    TechnicalIndicatorSeriesArtifactData,
    TechnicalPatternPackArtifactData,
)


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
    summary: dict[str, object]


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
        rsi_alert = _rsi_alert(frame.series.get("RSI_14", {}), timeframe)
        if rsi_alert:
            alerts.append(rsi_alert)

        fd_alerts = _fd_alerts(frame.series.get("FD_ZSCORE", {}), timeframe)
        alerts.extend(fd_alerts)
    return alerts


def _rsi_alert(series: dict[str, float | None], timeframe: str) -> AlertSignal | None:
    timestamp, value = _latest_value(series)
    if value is None:
        return None

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
        )
    return None


def _fd_alerts(series: dict[str, float | None], timeframe: str) -> list[AlertSignal]:
    alerts: list[AlertSignal] = []
    timestamp, value = _latest_value(series)
    if value is None:
        return alerts
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
            )
        )
    return alerts


def _build_breakout_alerts(
    pattern_pack: TechnicalPatternPackArtifactData,
) -> list[AlertSignal]:
    alerts: list[AlertSignal] = []
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


def _build_summary(alerts: list[AlertSignal]) -> dict[str, object]:
    severity_counts = {"critical": 0, "warning": 0, "info": 0}
    for alert in alerts:
        if alert.severity in severity_counts:
            severity_counts[alert.severity] += 1
    return {
        "total": len(alerts),
        "severity_counts": severity_counts,
        "generated_at": datetime.now().isoformat(),
    }
