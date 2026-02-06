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
