"""
Mapper layer for Fundamental Analysis agent.
Transforms complex financial data into lightweight preview data for UI rendering.
"""


def summarize_fundamental_for_preview(
    ctx: dict, financial_reports: list[dict] | None = None
) -> dict:
    """
    Generate preview data for Fundamental Analysis UI (<1KB).

    Args:
        ctx: FundamentalAnalysisContext dictionary
        financial_reports: Optional list of full financial reports

    Returns:
        Dictionary with preview data for immediate UI rendering
    """
    ticker = ctx.get("ticker", "UNKNOWN")
    model_type = ctx.get("selected_model") or ctx.get("model_type") or "Standard DCF"

    # Extract basics from context
    preview = {
        "ticker": ticker,
        "company_name": ctx.get("company_name", ticker),
        "selected_model": model_type,
        "sector": ctx.get("sector", "Unknown"),
        "industry": ctx.get("industry", "Unknown"),
        "valuation_score": ctx.get("valuation_score"),
        "status": ctx.get("status", "done"),
        "key_metrics": {},
    }

    # If we have reports, extract specific metrics for the preview
    if financial_reports and len(financial_reports) > 0:
        latest = financial_reports[0]
        # Handle both dict and Pydantic-like objects (though here they should be dicts from state)
        base = latest.get("base", {})

        # Helper to extract value and format
        def get_fmt_val(field_name: str, is_currency: bool = False) -> str:
            field = base.get(field_name)
            if field is None:
                return "N/A"
            val = field.get("value") if isinstance(field, dict) else field
            if val is None:
                return "N/A"
            try:
                fval = float(val)
                if is_currency:
                    if abs(fval) >= 1_000_000_000:
                        return f"${fval/1_000_000_000:.1f}B"
                    if abs(fval) >= 1_000_000:
                        return f"${fval/1_000_000:.1f}M"
                    return f"${fval:,.0f}"
                return f"{fval:,.2f}"
            except (ValueError, TypeError):
                return str(val)

        # Extract a few key metrics
        preview["key_metrics"] = {
            "Revenue": get_fmt_val("total_revenue", True),
            "Net Income": get_fmt_val("net_income", True),
            "Total Assets": get_fmt_val("total_assets", True),
        }

        # Calculate ROE if possible
        ni = (
            base.get("net_income", {}).get("value")
            if isinstance(base.get("net_income"), dict)
            else base.get("net_income")
        )
        eq = (
            base.get("total_equity", {}).get("value")
            if isinstance(base.get("total_equity"), dict)
            else base.get("total_equity")
        )
        if ni is not None and eq is not None and eq != 0:
            try:
                roe = float(ni) / float(eq)
                preview["key_metrics"]["ROE"] = f"{roe:.1%}"
            except Exception:
                pass

    return preview
