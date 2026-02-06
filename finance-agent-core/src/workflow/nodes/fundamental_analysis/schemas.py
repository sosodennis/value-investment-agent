from pydantic import BaseModel


class FundamentalAnalysisPreview(BaseModel):
    """Preview data for Fundamental Analysis UI (<1KB)."""

    ticker: str
    company_name: str
    selected_model: str
    sector: str
    industry: str
    valuation_score: float | None = None
    key_metrics: dict[str, str] = {}  # e.g., {"ROE": "15.2%", "Debt/Equity": "0.45"}
    status: str
