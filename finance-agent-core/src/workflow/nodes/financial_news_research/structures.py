from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


# --- Enums for Standardization ---
class SentimentLabel(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class ImpactLevel(str, Enum):
    HIGH = "high"  # e.g., Earnings miss, M&A, CEO fired
    MEDIUM = "medium"  # e.g., Product launch, Analyst upgrade
    LOW = "low"  # e.g., Routine PR, General commentary


class AssetClass(str, Enum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    FOREX = "forex"
    COMMODITY = "commodity"
    MACRO = "macro"  # e.g., CPI data, Fed rate


# --- Sub-Models ---
class SourceInfo(BaseModel):
    name: str = Field(..., description="Source name, e.g., Bloomberg, Reuters, WSJ")
    domain: str = Field(..., description="Source domain, used for authority assessment")
    reliability_score: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Source reliability weight (0-1)"
    )
    author: str | None = None


class FinancialEntity(BaseModel):
    ticker: str = Field(..., description="Stock ticker, e.g., AAPL")
    company_name: str
    relevance_score: float = Field(..., description="Entity relevance to news (0-1)")


class AIAnalysis(BaseModel):
    summary: str = Field(..., description="One-sentence financial summary by LLM")
    sentiment: SentimentLabel
    sentiment_score: float = Field(
        ..., description="-1.0 (Very Negative) to 1.0 (Very Positive)"
    )
    impact_level: ImpactLevel
    key_event: str | None = Field(
        None, description="Key event identified, e.g., 'Q3 Earnings Report'"
    )
    reasoning: str = Field(..., description="LLM reasoning for significance")


# --- Main Model ---
class FinancialNewsItem(BaseModel):
    # Identity & Access
    id: str = Field(..., description="Hash ID based on URL or Title for deduplication")
    url: HttpUrl

    # Metadata
    published_at: datetime | None = Field(None, description="Standardized UTC time")
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    # Content
    title: str
    snippet: str = Field(
        ..., description="Original snapshot/snippet from search engine"
    )
    full_content: str | None = Field(None, description="Cleaned full text if fetched")

    # Structured Data
    source: SourceInfo
    related_tickers: list[FinancialEntity] = Field(default_factory=list)
    tags: list[str] = Field(
        default_factory=list, description="e.g., 'Earnings', 'Regulation', 'IPO'"
    )

    # AI Enrichment
    finbert_analysis: dict | None = None  # Local FinBERT pre-filter results
    analysis: AIAnalysis | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "a1b2c3d4",
                "title": "Apple Shares Drop on iPhone Shipment Concerns",
                "published_at": "2024-05-21T14:30:00Z",
                "related_tickers": [
                    {
                        "ticker": "AAPL",
                        "company_name": "Apple Inc.",
                        "relevance_score": 0.95,
                    }
                ],
                "analysis": {
                    "summary": "Apple stock declined due to shipment warnings.",
                    "sentiment": "bearish",
                    "sentiment_score": -0.6,
                    "impact_level": "high",
                    "reasoning": "Supply chain issues directly affect revenue guidance.",
                },
            }
        }
    )


class NewsResearchOutput(BaseModel):
    """Final output for news research sub-graph."""

    ticker: str
    news_items: list[FinancialNewsItem] = Field(default_factory=list)
    overall_sentiment: SentimentLabel = Field(default=SentimentLabel.NEUTRAL)
    sentiment_score: float = Field(
        default=0.0, description="Weighted average sentiment score (-1 to 1)"
    )
    key_themes: list[str] = Field(
        default_factory=list, description="Aggregated key themes"
    )
