from pydantic import BaseModel, Field


class BaseValuationParams(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol")
    rationale: str = Field(
        ..., description="Reasoning behind the parameter assumptions, with citations."
    )
