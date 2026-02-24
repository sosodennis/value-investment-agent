from __future__ import annotations

from src.shared.kernel.types import JSONObject


def _format_metric_value(value: object, *, is_currency: bool) -> str:
    if value is None:
        return "N/A"
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    if not is_currency:
        return f"{numeric:,.2f}"
    if abs(numeric) >= 1_000_000_000:
        return f"${numeric/1_000_000_000:.1f}B"
    if abs(numeric) >= 1_000_000:
        return f"${numeric/1_000_000:.1f}M"
    return f"${numeric:,.0f}"


def format_fundamental_preview(view_model: JSONObject) -> JSONObject:
    metrics_raw = view_model.get("metrics")
    metrics = metrics_raw if isinstance(metrics_raw, dict) else {}
    assumption_breakdown_raw = view_model.get("assumption_breakdown")
    assumption_breakdown = (
        assumption_breakdown_raw if isinstance(assumption_breakdown_raw, dict) else None
    )
    data_freshness_raw = view_model.get("data_freshness")
    data_freshness = (
        data_freshness_raw if isinstance(data_freshness_raw, dict) else None
    )
    assumption_risk_level_raw = view_model.get("assumption_risk_level")
    assumption_risk_level = (
        assumption_risk_level_raw
        if isinstance(assumption_risk_level_raw, str) and assumption_risk_level_raw
        else None
    )
    data_quality_flags_raw = view_model.get("data_quality_flags")
    data_quality_flags = (
        [item for item in data_quality_flags_raw if isinstance(item, str) and item]
        if isinstance(data_quality_flags_raw, list)
        else None
    )
    time_alignment_status_raw = view_model.get("time_alignment_status")
    time_alignment_status = (
        time_alignment_status_raw
        if isinstance(time_alignment_status_raw, str) and time_alignment_status_raw
        else None
    )
    forward_signal_summary_raw = view_model.get("forward_signal_summary")
    forward_signal_summary = (
        forward_signal_summary_raw
        if isinstance(forward_signal_summary_raw, dict)
        else None
    )
    forward_signal_risk_level_raw = view_model.get("forward_signal_risk_level")
    forward_signal_risk_level = (
        forward_signal_risk_level_raw
        if isinstance(forward_signal_risk_level_raw, str)
        and forward_signal_risk_level_raw
        else None
    )
    forward_signal_evidence_count_raw = view_model.get("forward_signal_evidence_count")
    forward_signal_evidence_count = (
        int(forward_signal_evidence_count_raw)
        if isinstance(forward_signal_evidence_count_raw, int | float)
        else None
    )

    key_metrics: JSONObject = {
        "Revenue": _format_metric_value(metrics.get("revenue_raw"), is_currency=True),
        "Net Income": _format_metric_value(
            metrics.get("net_income_raw"), is_currency=True
        ),
        "Total Assets": _format_metric_value(
            metrics.get("total_assets_raw"), is_currency=True
        ),
    }
    roe_ratio = metrics.get("roe_ratio")
    if isinstance(roe_ratio, int | float):
        key_metrics["ROE"] = f"{float(roe_ratio):.1%}"

    preview: JSONObject = {
        "ticker": view_model.get("ticker", "UNKNOWN"),
        "company_name": view_model.get(
            "company_name", view_model.get("ticker", "UNKNOWN")
        ),
        "selected_model": view_model.get("selected_model", "Standard DCF"),
        "sector": view_model.get("sector", "Unknown"),
        "industry": view_model.get("industry", "Unknown"),
        "valuation_score": view_model.get("valuation_score"),
        "status": view_model.get("status", "done"),
        "key_metrics": key_metrics if metrics else {},
    }
    if assumption_breakdown is not None:
        preview["assumption_breakdown"] = assumption_breakdown
    if data_freshness is not None:
        preview["data_freshness"] = data_freshness
    if assumption_risk_level is not None:
        preview["assumption_risk_level"] = assumption_risk_level
    if data_quality_flags is not None:
        preview["data_quality_flags"] = data_quality_flags
    if time_alignment_status is not None:
        preview["time_alignment_status"] = time_alignment_status
    if forward_signal_summary is not None:
        preview["forward_signal_summary"] = forward_signal_summary
    if forward_signal_risk_level is not None:
        preview["forward_signal_risk_level"] = forward_signal_risk_level
    if forward_signal_evidence_count is not None:
        preview["forward_signal_evidence_count"] = forward_signal_evidence_count
    return preview
