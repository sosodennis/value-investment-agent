from pydantic import BaseModel, Field


class NewsPreview(BaseModel):
    """Preview data for Financial News UI (<1KB)."""

    status_label: str = Field(..., description="Status display text")
    sentiment_display: str = Field(..., description="Sentiment with emoji and score")
    article_count_display: str = Field(..., description="Article count display text")
    top_headlines: list[str] = Field(
        default_factory=list, max_length=3, description="Top 3 headlines"
    )
