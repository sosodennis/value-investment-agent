from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from src.interface.artifacts.artifact_model_shared import validate_and_dump
from src.shared.kernel.types import JSONObject

from .types import (
    ImpactToken,
    NewsCategoryTokenList,
    NewsNumber,
    NewsStringList,
    NewsText,
    OptionalNewsText,
    SentimentToken,
)


class SourceInfoModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: NewsText
    domain: NewsText
    reliability_score: NewsNumber
    author: OptionalNewsText = None


class NewsSearchResultItemModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: NewsText
    source: NewsText
    snippet: NewsText
    link: NewsText
    date: OptionalNewsText = None
    image: OptionalNewsText = None
    categories: NewsStringList = Field(default_factory=list)


class FinancialEntityModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: NewsText
    company_name: NewsText
    relevance_score: NewsNumber


class KeyFactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: NewsText
    is_quantitative: bool
    sentiment: SentimentToken
    citation: OptionalNewsText = None


class AIAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: NewsText
    sentiment: SentimentToken
    sentiment_score: NewsNumber
    impact_level: ImpactToken
    key_event: OptionalNewsText = None
    reasoning: NewsText
    key_facts: list[KeyFactModel] = Field(default_factory=list)


class FinancialNewsItemModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: NewsText
    url: NewsText
    published_at: OptionalNewsText = None
    fetched_at: NewsText = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    title: NewsText
    snippet: NewsText
    full_content: OptionalNewsText = None
    content_id: OptionalNewsText = None
    source: SourceInfoModel
    related_tickers: list[FinancialEntityModel] = Field(default_factory=list)
    categories: NewsCategoryTokenList = Field(default_factory=list)
    tags: NewsStringList = Field(default_factory=list)
    analysis: AIAnalysisModel | None = None


class NewsArtifactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: NewsText
    news_items: list[FinancialNewsItemModel]
    overall_sentiment: SentimentToken
    sentiment_score: NewsNumber
    key_themes: NewsStringList


def parse_news_artifact_model(value: object) -> JSONObject:
    return validate_and_dump(
        NewsArtifactModel,
        value,
        "news artifact",
        exclude_none=True,
    )
