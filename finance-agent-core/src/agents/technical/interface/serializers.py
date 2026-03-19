from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime

from pydantic import BaseModel

from src.agents.technical.domain.shared import FeatureSummary
from src.agents.technical.subdomains.signal_fusion import (
    DirectionScorecard,
    IndicatorContribution,
    safe_float,
)
from src.agents.technical.subdomains.verification.domain import (
    BacktestSummary,
    VerificationGateResult,
    WfaSummary,
)
from src.interface.artifacts.artifact_data_models import (
    TechnicalFeaturePackArtifactData,
    TechnicalFusionReportArtifactData,
)
from src.shared.kernel.types import JSONObject


def build_data_fetch_preview(*, ticker: str, latest_price: object) -> JSONObject:
    latest_price_num = safe_float(latest_price)
    latest_price_display = (
        f"${latest_price_num:,.2f}" if latest_price_num is not None else "N/A"
    )
    return {
        "ticker": ticker,
        "latest_price_display": latest_price_display,
        "signal_display": "📊 FETCHING DATA...",
        "z_score_display": "Z: N/A",
        "optimal_d_display": "d=N/A",
        "strength_display": "Strength: N/A",
    }


def build_fracdiff_progress_preview(
    *,
    ticker: str,
    latest_price: object,
    z_score: object,
    optimal_d: object,
    statistical_strength: object,
) -> JSONObject:
    latest_price_num = safe_float(latest_price) or 0.0
    z_score_num = safe_float(z_score) or 0.0
    optimal_d_num = safe_float(optimal_d) or 0.0
    strength_num = safe_float(statistical_strength) or 0.0

    return {
        "ticker": ticker,
        "latest_price_display": f"${latest_price_num:,.2f}",
        "signal_display": "🧬 COMPUTING...",
        "z_score_display": f"Z: {z_score_num:+.2f}",
        "optimal_d_display": f"d={optimal_d_num:.2f}",
        "strength_display": f"Strength: {strength_num:.1f}",
    }


def build_feature_compute_preview(
    *,
    ticker: str,
    classic_count: object,
    quant_count: object,
    timeframe_count: object,
) -> JSONObject:
    classic_num = safe_float(classic_count) or 0.0
    quant_num = safe_float(quant_count) or 0.0
    timeframe_num = safe_float(timeframe_count) or 0.0
    return {
        "ticker": ticker,
        "latest_price_display": "N/A",
        "signal_display": "📈 FEATURES READY",
        "z_score_display": f"Classic: {classic_num:.0f}",
        "optimal_d_display": f"Quant: {quant_num:.0f}",
        "strength_display": f"Frames: {timeframe_num:.0f}",
    }


def build_pattern_compute_preview(
    *,
    ticker: str,
    support_count: object,
    resistance_count: object,
    breakout_count: object,
) -> JSONObject:
    support_num = safe_float(support_count) or 0.0
    resistance_num = safe_float(resistance_count) or 0.0
    breakout_num = safe_float(breakout_count) or 0.0
    return {
        "ticker": ticker,
        "latest_price_display": "N/A",
        "signal_display": "📐 PATTERNS READY",
        "z_score_display": f"Support: {support_num:.0f}",
        "optimal_d_display": f"Resist: {resistance_num:.0f}",
        "strength_display": f"Breakouts: {breakout_num:.0f}",
    }


def build_fusion_compute_preview(
    *,
    ticker: str,
    direction: object,
    risk_level: object,
    confidence: object,
) -> JSONObject:
    direction_text = str(direction or "N/A").upper()
    risk_text = str(risk_level or "N/A").upper()
    conf_num = safe_float(confidence)
    conf_text = f"Conf: {conf_num:.2f}" if conf_num is not None else "Conf: N/A"
    return {
        "ticker": ticker,
        "latest_price_display": "N/A",
        "signal_display": "🧭 FUSION READY",
        "z_score_display": f"Dir: {direction_text}",
        "optimal_d_display": f"Risk: {risk_text}",
        "strength_display": conf_text,
    }


def build_regime_compute_preview(
    *,
    ticker: str,
    dominant_regime: object,
    timeframe_count: object,
    degraded_count: object,
) -> JSONObject:
    regime_text = str(dominant_regime or "N/A").upper()
    timeframe_num = safe_float(timeframe_count) or 0.0
    degraded_num = safe_float(degraded_count) or 0.0
    return {
        "ticker": ticker,
        "latest_price_display": "N/A",
        "signal_display": "🌦️ REGIME READY",
        "z_score_display": f"Regime: {regime_text}",
        "optimal_d_display": f"Frames: {timeframe_num:.0f}",
        "strength_display": f"Degraded: {degraded_num:.0f}",
    }


def build_verification_compute_preview(
    *,
    ticker: str,
    baseline_status: object,
    trade_count: object,
    wfe_ratio: object,
) -> JSONObject:
    status_text = str(baseline_status or "N/A").upper()
    trades_num = safe_float(trade_count) or 0.0
    wfe_num = safe_float(wfe_ratio)
    wfe_text = f"WFE: {wfe_num:.2f}" if wfe_num is not None else "WFE: N/A"
    return {
        "ticker": ticker,
        "latest_price_display": "N/A",
        "signal_display": "🧪 VERIFICATION READY",
        "z_score_display": f"Gate: {status_text}",
        "optimal_d_display": f"Trades: {trades_num:.0f}",
        "strength_display": wfe_text,
    }


def build_alerts_compute_preview(
    *,
    ticker: str,
    alert_count: object,
    critical_count: object,
) -> JSONObject:
    alert_num = safe_float(alert_count) or 0.0
    critical_num = safe_float(critical_count) or 0.0
    return {
        "ticker": ticker,
        "latest_price_display": "N/A",
        "signal_display": "🚨 ALERTS READY",
        "z_score_display": f"Alerts: {alert_num:.0f}",
        "optimal_d_display": f"Critical: {critical_num:.0f}",
        "strength_display": "Threshold + Breakout",
    }


def build_feature_pack_artifact_payload(
    feature_pack: object,
    *,
    degraded_reasons: list[str],
) -> JSONObject:
    if isinstance(feature_pack, TechnicalFeaturePackArtifactData):
        payload = feature_pack.model_dump(mode="json")
        if isinstance(payload, dict):
            return payload
    if not hasattr(feature_pack, "__dict__"):
        raise TypeError("feature_pack must be serializable")

    data = feature_pack.__dict__.copy()
    timeframes = data.get("timeframes", {})
    serialized_timeframes: dict[str, object] = {}
    for key, frame in timeframes.items():
        serialized_timeframes[str(key)] = {
            "classic_indicators": _serialize_indicators(
                getattr(frame, "classic_indicators", {})
            ),
            "quant_features": _serialize_indicators(
                getattr(frame, "quant_features", {})
            ),
        }

    return {
        "ticker": data.get("ticker"),
        "as_of": data.get("as_of"),
        "timeframes": serialized_timeframes,
        "feature_summary": _serialize_feature_summary(data.get("feature_summary")),
        "degraded_reasons": degraded_reasons or None,
    }


def build_indicator_series_artifact_payload(result: object) -> JSONObject:
    timeframes = getattr(result, "timeframes", None)
    if not isinstance(timeframes, Mapping):
        raise TypeError("indicator series result must expose timeframes")
    timeframes_payload: dict[str, object] = {}
    for key, frame in timeframes.items():
        timeframes_payload[str(key)] = {
            "timeframe": getattr(frame, "timeframe", None),
            "start": getattr(frame, "start", None),
            "end": getattr(frame, "end", None),
            "series": getattr(frame, "series", None),
            "timezone": getattr(frame, "timezone", None),
            "metadata": _serialize_dataclass_like(getattr(frame, "metadata", None))
            or None,
        }
    return {
        "ticker": getattr(result, "ticker", None),
        "as_of": getattr(result, "as_of", None),
        "timeframes": timeframes_payload,
        "degraded_reasons": getattr(result, "degraded_reasons", None) or None,
    }


def build_alignment_report_payload(report: object) -> dict[str, object]:
    if hasattr(report, "__dict__"):
        return dict(report.__dict__)
    return {}


def build_fusion_report_artifact_payload(
    result: object,
    *,
    alignment_report: dict[str, object] | None,
    feature_pack_id: str | None,
    pattern_pack_id: str | None,
    regime_pack_id: str | None,
    timeseries_bundle_id: str | None,
    degraded_reasons: list[str],
    confidence_raw: float | None,
    confidence_calibrated: float | None,
    signal_strength_raw: float | None,
    signal_strength_effective: float | None,
    confidence_calibration: dict[str, object] | None,
    confidence_eligibility: dict[str, object] | None,
) -> JSONObject:
    if isinstance(result, TechnicalFusionReportArtifactData):
        payload = result.model_dump(mode="json")
        if isinstance(payload, dict):
            return payload

    fusion_result = result
    fusion_signal = fusion_result.fusion_signal
    diagnostics = fusion_signal.diagnostics

    return {
        "schema_version": "1.0",
        "ticker": fusion_signal.ticker,
        "as_of": fusion_signal.as_of,
        "direction": fusion_signal.direction,
        "risk_level": fusion_signal.risk_level,
        "confidence": confidence_calibrated,
        "confidence_raw": confidence_raw,
        "confidence_calibrated": confidence_calibrated,
        "signal_strength_raw": signal_strength_raw,
        "signal_strength_effective": signal_strength_effective,
        "confidence_calibration": confidence_calibration,
        "confidence_eligibility": confidence_eligibility,
        "confluence_matrix": diagnostics.confluence_matrix if diagnostics else {},
        "conflict_reasons": diagnostics.conflict_reasons if diagnostics else [],
        "regime_summary": (
            fusion_result.scorecard.regime_summary if fusion_result.scorecard else {}
        ),
        "alignment_report": alignment_report,
        "source_artifacts": {
            "timeseries_bundle_id": timeseries_bundle_id,
            "feature_pack_id": feature_pack_id,
            "pattern_pack_id": pattern_pack_id,
            "regime_pack_id": regime_pack_id,
        },
        "degraded_reasons": list(degraded_reasons),
    }


def build_direction_scorecard_artifact_payload(
    scorecard: DirectionScorecard,
    *,
    degraded_reasons: list[str],
    source_artifacts: dict[str, str | None],
) -> JSONObject:
    frames: dict[str, dict[str, object]] = {}
    for timeframe, frame in scorecard.timeframes.items():
        frames[timeframe] = {
            "timeframe": frame.timeframe,
            "base_total_score": frame.base_total_score,
            "classic_score": frame.classic_score,
            "quant_score": frame.quant_score,
            "pattern_score": frame.pattern_score,
            "total_score": frame.total_score,
            "classic_label": frame.classic_label,
            "quant_label": frame.quant_label,
            "pattern_label": frame.pattern_label,
            "regime": frame.regime,
            "regime_directional_bias": frame.regime_directional_bias,
            "regime_weight_multiplier": frame.regime_weight_multiplier,
            "regime_notes": list(frame.regime_notes),
            "contributions": _scorecard_contributions_payload(frame.contributions),
        }

    return {
        "schema_version": "1.0",
        "ticker": scorecard.ticker,
        "as_of": scorecard.as_of,
        "direction": scorecard.direction,
        "risk_level": scorecard.risk_level,
        "confidence": scorecard.confidence,
        "neutral_threshold": scorecard.neutral_threshold,
        "overall_score": scorecard.overall_score,
        "model_version": scorecard.model_version,
        "regime_summary": dict(scorecard.regime_summary),
        "timeframes": frames,
        "conflict_reasons": list(scorecard.conflict_reasons),
        "degraded_reasons": list(degraded_reasons),
        "source_artifacts": dict(source_artifacts),
    }


def build_verification_report_payload(
    *,
    ticker: str,
    as_of: str,
    backtest_summary: BacktestSummary | None,
    wfa_summary: WfaSummary | None,
    baseline_gates: VerificationGateResult | None,
    robustness_flags: list[str],
    source_artifacts: dict[str, str | None] | None,
    degraded_reasons: list[str],
) -> JSONObject:
    return {
        "schema_version": "1.0",
        "ticker": ticker,
        "as_of": as_of,
        "backtest_summary": _serialize_backtest_summary(backtest_summary),
        "wfa_summary": _serialize_wfa_summary(wfa_summary),
        "robustness_flags": robustness_flags or None,
        "baseline_gates": _serialize_gate_result(baseline_gates),
        "source_artifacts": source_artifacts,
        "degraded_reasons": degraded_reasons or None,
    }


def _serialize_backtest_summary(
    summary: BacktestSummary | None,
) -> dict[str, float | int | str | None] | None:
    if summary is None:
        return None
    return {
        "strategy_name": summary.strategy_name,
        "win_rate": summary.win_rate,
        "profit_factor": summary.profit_factor,
        "sharpe_ratio": summary.sharpe_ratio,
        "max_drawdown": summary.max_drawdown,
        "total_trades": summary.total_trades,
    }


def _serialize_wfa_summary(
    summary: WfaSummary | None,
) -> dict[str, float | int | None] | None:
    if summary is None:
        return None
    return {
        "wfa_sharpe": summary.wfa_sharpe,
        "wfe_ratio": summary.wfe_ratio,
        "wfa_max_drawdown": summary.wfa_max_drawdown,
        "period_count": summary.period_count,
    }


def _serialize_gate_result(
    gate: VerificationGateResult | None,
) -> dict[str, object] | None:
    if gate is None:
        return None
    issues: list[dict[str, object]] = []
    for issue in gate.issues:
        issues.append(
            {
                "code": issue.code,
                "message": issue.message,
                "blocking": issue.blocking,
                "metric": issue.metric,
                "actual": issue.actual,
                "threshold": issue.threshold,
            }
        )
    return {
        "status": gate.status,
        "policy_version": gate.policy_version,
        "blocking_count": gate.blocking_count,
        "warning_count": gate.warning_count,
        "issue_count": len(issues),
        "issues": issues,
    }


def build_full_report_payload(
    *,
    ticker: str,
    technical_context: JSONObject,
    tags_dict: JSONObject,
    analyst_perspective: JSONObject,
    raw_data: JSONObject,
) -> JSONObject:
    confidence = technical_context.get("confidence")
    confidence_val = float(confidence) if isinstance(confidence, int | float) else None
    confidence_raw = technical_context.get("confidence_raw")
    confidence_raw_val = (
        float(confidence_raw) if isinstance(confidence_raw, int | float) else None
    )
    confidence_calibrated = technical_context.get("confidence_calibrated")
    confidence_calibrated_val = (
        float(confidence_calibrated)
        if isinstance(confidence_calibrated, int | float)
        else None
    )
    if confidence_val is None and confidence_calibrated_val is not None:
        confidence_val = confidence_calibrated_val
    signal_strength_raw = technical_context.get("signal_strength_raw")
    signal_strength_raw_val = (
        float(signal_strength_raw)
        if isinstance(signal_strength_raw, int | float)
        else None
    )
    signal_strength_effective = technical_context.get("signal_strength_effective")
    signal_strength_effective_val = (
        float(signal_strength_effective)
        if isinstance(signal_strength_effective, int | float)
        else None
    )
    confidence_calibration = _optional_object_payload(
        technical_context.get("confidence_calibration")
    )
    confidence_eligibility = _optional_object_payload(
        technical_context.get("confidence_eligibility")
    )
    momentum_extremes = _optional_object_payload(
        technical_context.get("momentum_extremes")
    )
    regime_summary = _optional_object_payload(technical_context.get("regime_summary"))
    volume_profile_summary = _optional_object_payload(
        technical_context.get("volume_profile_summary")
    )
    structure_confluence_summary = _optional_object_payload(
        technical_context.get("structure_confluence_summary")
    )
    evidence_bundle = _optional_object_payload(technical_context.get("evidence_bundle"))
    signal_strength_summary = _optional_object_payload(
        technical_context.get("signal_strength_summary")
    )
    setup_reliability_summary = _optional_object_payload(
        technical_context.get("setup_reliability_summary")
    )
    quality_summary = _optional_object_payload(technical_context.get("quality_summary"))
    alert_readout = _optional_object_payload(technical_context.get("alert_readout"))
    observability_summary = _optional_object_payload(
        technical_context.get("observability_summary")
    )
    return {
        "schema_version": "2.0",
        "ticker": ticker,
        "as_of": datetime.now().isoformat(),
        "direction": str(tags_dict.get("direction") or "NEUTRAL").upper(),
        "risk_level": str(tags_dict.get("risk_level") or "medium").lower(),
        "confidence": confidence_val,
        "confidence_raw": confidence_raw_val,
        "confidence_calibrated": confidence_calibrated_val,
        "signal_strength_raw": signal_strength_raw_val,
        "signal_strength_effective": signal_strength_effective_val,
        "confidence_calibration": confidence_calibration,
        "confidence_eligibility": confidence_eligibility,
        "momentum_extremes": momentum_extremes,
        "regime_summary": regime_summary,
        "volume_profile_summary": volume_profile_summary,
        "structure_confluence_summary": structure_confluence_summary,
        "evidence_bundle": evidence_bundle,
        "signal_strength_summary": signal_strength_summary,
        "setup_reliability_summary": setup_reliability_summary,
        "quality_summary": quality_summary,
        "alert_readout": alert_readout,
        "observability_summary": observability_summary,
        "analyst_perspective": analyst_perspective,
        "artifact_refs": {
            "chart_data_id": technical_context.get("chart_data_id"),
            "timeseries_bundle_id": technical_context.get("timeseries_bundle_id"),
            "indicator_series_id": technical_context.get("indicator_series_id"),
            "alerts_id": technical_context.get("alerts_id"),
            "feature_pack_id": technical_context.get("feature_pack_id"),
            "pattern_pack_id": technical_context.get("pattern_pack_id"),
            "regime_pack_id": technical_context.get("regime_pack_id"),
            "fusion_report_id": technical_context.get("fusion_report_id"),
            "direction_scorecard_id": technical_context.get("direction_scorecard_id"),
            "verification_report_id": technical_context.get("verification_report_id"),
        },
        "summary_tags": tags_dict.get("tags", []),
        "diagnostics": {
            "is_degraded": technical_context.get("is_degraded"),
            "degraded_reasons": technical_context.get("degraded_reasons"),
        },
    }


def _optional_object_payload(value: object) -> JSONObject | None:
    if isinstance(value, BaseModel):
        dumped = value.model_dump(mode="json", exclude_none=True)
        return dumped if isinstance(dumped, dict) else None
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _serialize_indicators(indicators: Mapping[str, object]) -> dict[str, object]:
    serialized: dict[str, object] = {}
    for key, indicator in indicators.items():
        if hasattr(indicator, "__dict__"):
            data = indicator.__dict__
            provenance = data.get("provenance")
            quality = data.get("quality")
            serialized[key] = {
                "name": data.get("name"),
                "value": data.get("value"),
                "state": data.get("state"),
                "provenance": _serialize_dataclass_like(provenance),
                "quality": _serialize_dataclass_like(quality),
                "metadata": data.get("metadata") or {},
            }
        elif isinstance(indicator, dict):
            serialized[key] = indicator
    return serialized


def _serialize_dataclass_like(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if is_dataclass(value):
        payload = asdict(value)
        quality_flags = payload.get("quality_flags")
        if isinstance(quality_flags, tuple):
            payload["quality_flags"] = list(quality_flags)
        return payload
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _serialize_feature_summary(value: object) -> dict[str, object]:
    if isinstance(value, FeatureSummary):
        payload = asdict(value)
        for key in (
            "ready_timeframes",
            "degraded_timeframes",
            "regime_inputs_ready_timeframes",
        ):
            entry = payload.get(key)
            if isinstance(entry, tuple):
                payload[key] = list(entry)
        return payload
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _scorecard_contributions_payload(
    contributions: dict[str, list[IndicatorContribution]],
) -> dict[str, list[dict[str, object]]]:
    payload: dict[str, list[dict[str, object]]] = {}
    for category, items in contributions.items():
        payload[category] = [_scorecard_contribution_payload(item) for item in items]
    return payload


def _scorecard_contribution_payload(
    item: IndicatorContribution,
) -> dict[str, object]:
    return {
        "name": item.name,
        "value": item.value,
        "state": item.state,
        "contribution": item.contribution,
        "weight": item.weight,
        "notes": item.notes,
    }
