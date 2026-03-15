from __future__ import annotations

from datetime import datetime

from src.agents.technical.subdomains.signal_fusion import safe_float
from src.agents.technical.subdomains.verification.domain import (
    BacktestSummary,
    VerificationGateResult,
    WfaSummary,
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
    llm_interpretation: str,
    raw_data: JSONObject,
) -> JSONObject:
    confidence = technical_context.get("confidence")
    confidence_val = float(confidence) if isinstance(confidence, int | float) else None
    return {
        "schema_version": "2.0",
        "ticker": ticker,
        "as_of": datetime.now().isoformat(),
        "direction": str(tags_dict.get("direction") or "NEUTRAL").upper(),
        "risk_level": str(tags_dict.get("risk_level") or "medium").lower(),
        "confidence": confidence_val,
        "llm_interpretation": llm_interpretation,
        "artifact_refs": {
            "chart_data_id": technical_context.get("chart_data_id"),
            "timeseries_bundle_id": technical_context.get("timeseries_bundle_id"),
            "indicator_series_id": technical_context.get("indicator_series_id"),
            "alerts_id": technical_context.get("alerts_id"),
            "feature_pack_id": technical_context.get("feature_pack_id"),
            "pattern_pack_id": technical_context.get("pattern_pack_id"),
            "fusion_report_id": technical_context.get("fusion_report_id"),
            "verification_report_id": technical_context.get("verification_report_id"),
        },
        "summary_tags": tags_dict.get("tags", []),
        "diagnostics": {
            "is_degraded": technical_context.get("is_degraded"),
            "degraded_reasons": technical_context.get("degraded_reasons"),
        },
    }
