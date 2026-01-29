from typing import Literal

from pydantic import BaseModel, Field

from .structures import NewsResearchOutput


class NewsPreview(BaseModel):
    """Preview data for Financial News UI (<1KB)."""

    status_label: str = Field(..., description="Status display text")
    sentiment_display: str = Field(..., description="Sentiment with emoji and score")
    article_count_display: str = Field(..., description="Article count display text")
    top_headlines: list[str] = Field(
        default_factory=list, max_length=3, description="Top 3 headlines"
    )


class FinancialNewsSuccess(NewsResearchOutput):
    """Successful news research result with discriminator."""

    kind: Literal["success"] = "success"


class FinancialNewsError(BaseModel):
    """Failure schema for news research."""

    kind: Literal["error"] = "error"
    message: str


FinancialNewsResult = FinancialNewsSuccess | FinancialNewsError
