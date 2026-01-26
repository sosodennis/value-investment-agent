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


FundamentalAnalysisResult = FundamentalAnalysisSuccess | FundamentalAnalysisError
