from typing import Literal

from pydantic import BaseModel


class FundamentalAnalysisSuccess(BaseModel):
    """Schema for successful model selection and financial report fetching."""

    kind: Literal["success"] = "success"
    ticker: str
    model_type: str
    company_name: str
    sector: str
    industry: str
    reasoning: str
    financial_reports: list[dict]
    status: Literal["done"] = "done"


class FundamentalAnalysisError(BaseModel):
    """Schema for fundamental analysis failures."""

    kind: Literal["error"] = "error"
    message: str


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


FundamentalAnalysisResult = FundamentalAnalysisSuccess | FundamentalAnalysisError
