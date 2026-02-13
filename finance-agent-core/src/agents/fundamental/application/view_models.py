from __future__ import annotations

from src.common.types import JSONObject


def _extract_traceable_value(base: JSONObject, field_name: str) -> object:
    field = base.get(field_name)
    if isinstance(field, dict):
        return field.get("value")
    return field


def _safe_ratio(numerator: object, denominator: object) -> float | None:
    try:
        num = float(numerator)  # type: ignore[arg-type]
        den = float(denominator)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if den == 0:
        return None
    return num / den


def derive_fundamental_preview_view_model(
    ctx: JSONObject,
    financial_reports: list[JSONObject] | None = None,
) -> JSONObject:
    ticker = str(ctx.get("ticker", "UNKNOWN"))
    selected_model = str(
        ctx.get("selected_model") or ctx.get("model_type") or "Standard DCF"
    )

    metrics: JSONObject = {}
    if financial_reports:
        latest = financial_reports[0]
        base_raw = latest.get("base")
        base = base_raw if isinstance(base_raw, dict) else {}

        revenue = _extract_traceable_value(base, "total_revenue")
        net_income = _extract_traceable_value(base, "net_income")
        total_assets = _extract_traceable_value(base, "total_assets")
        total_equity = _extract_traceable_value(base, "total_equity")
        roe_ratio = _safe_ratio(net_income, total_equity)

        metrics = {
            "revenue_raw": revenue,
            "net_income_raw": net_income,
            "total_assets_raw": total_assets,
            "roe_ratio": roe_ratio,
        }

    return {
        "ticker": ticker,
        "company_name": ctx.get("company_name", ticker),
        "selected_model": selected_model,
        "sector": ctx.get("sector", "Unknown"),
        "industry": ctx.get("industry", "Unknown"),
        "valuation_score": ctx.get("valuation_score"),
        "status": ctx.get("status", "done"),
        "metrics": metrics,
    }
