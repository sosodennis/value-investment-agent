from typing import Literal

from pydantic import BaseModel, Field


class IntentExtractionPreview(BaseModel):
    """
    L2 Preview (Hot Data) for Intent Extraction UI.
    Contains critical information for immediate rendering.
    """

    ticker: str | None = Field(None, description="Resolved ticker symbol")
    company_name: str | None = Field(None, description="Company name")
    status_label: str = Field(
        ..., description="UI status label (e.g., 解析中, 搜索中, 已確認)"
    )
    exchange: str | None = Field(None, description="Stock exchange (e.g., NASDAQ)")


class IntentExtractionSuccess(BaseModel):
    """Schema for successful ticker resolution."""

    kind: Literal["success"] = "success"
    resolved_ticker: str
    company_profile: dict
    status: Literal["resolved"] = "resolved"


class IntentExtractionError(BaseModel):
    """Schema for intentional extraction failures."""

    kind: Literal["error"] = "error"
    message: str


# Composite type for the adapter/mapper validation
IntentExtractionOutput = IntentExtractionSuccess | IntentExtractionError
