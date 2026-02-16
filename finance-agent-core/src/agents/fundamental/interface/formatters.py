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

    return {
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
