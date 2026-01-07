from pydantic import BaseModel, Field


class NewsResearchOutput(BaseModel):
    """Structured output for news research."""

    summary: str = Field(
        ..., description="A concise summary of recent news and developments."
    )
    sentiment: str = Field(
        ..., description="Overall market sentiment (Bullish, Bearish, or Neutral)."
    )
    key_themes: list[str] = Field(
        default_factory=list, description="List of key themes or events."
    )
