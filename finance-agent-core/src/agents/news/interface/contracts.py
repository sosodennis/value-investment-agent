from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.common.types import JSONObject
from src.interface.artifact_model_shared import (
    symbol,
    to_number,
    to_optional_string,
    to_string,
    validate_and_dump,
)

SENTIMENT_MAP: dict[str, str] = {
    "bullish": "bullish",
    "bearish": "bearish",
    "neutral": "neutral",
}

IMPACT_MAP: dict[str, str] = {
    "high": "high",
    "medium": "medium",
    "low": "low",
}

CATEGORY_MAP: dict[str, str] = {
    "general": "general",
    "corporate_event": "corporate_event",
    "corporateevent": "corporate_event",
    "financials": "financials",
    "trusted_news": "trusted_news",
    "trustednews": "trusted_news",
    "analyst_opinion": "analyst_opinion",
    "analystopinion": "analyst_opinion",
    "bullish": "bullish",
    "bearish": "bearish",
}


class SourceInfoModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    domain: str
    reliability_score: float
    author: str | None = None

    @field_validator("name", "domain", mode="before")
    @classmethod
    def _name_domain(cls, value: object) -> str:
        return to_string(value, "source field")

    @field_validator("reliability_score", mode="before")
    @classmethod
    def _score(cls, value: object) -> float:
        return to_number(value, "source.reliability_score")

    @field_validator("author", mode="before")
    @classmethod
    def _author(cls, value: object) -> str | None:
        return to_optional_string(value, "source.author")


class NewsSearchResultItemModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    source: str
    snippet: str
    link: str
    date: str | None = None
    image: str | None = None
    categories: list[str] = Field(default_factory=list)

    @field_validator("title", "source", "snippet", "link", mode="before")
    @classmethod
    def _required_text(cls, value: object) -> str:
        return to_string(value, "search result field")

    @field_validator("date", "image", mode="before")
    @classmethod
    def _optional_text(cls, value: object) -> str | None:
        return to_optional_string(value, "search result optional field")

    @field_validator("categories", mode="before")
    @classmethod
    def _categories(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise TypeError("search result.categories must be a list")
        return [to_string(item, "search result.categories[]") for item in value]


class FinancialEntityModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    company_name: str
    relevance_score: float

    @field_validator("ticker", "company_name", mode="before")
    @classmethod
    def _string_field(cls, value: object) -> str:
        return to_string(value, "financial_entity field")

    @field_validator("relevance_score", mode="before")
    @classmethod
    def _relevance(cls, value: object) -> float:
        return to_number(value, "financial_entity.relevance_score")


class KeyFactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str
    is_quantitative: bool
    sentiment: Literal["bullish", "bearish", "neutral"]
    citation: str | None = None

    @field_validator("content", mode="before")
    @classmethod
    def _content(cls, value: object) -> str:
        return to_string(value, "key_fact.content")

    @field_validator("sentiment", mode="before")
    @classmethod
    def _sentiment(cls, value: object) -> str:
        return symbol(value, "key_fact.sentiment", SENTIMENT_MAP)

    @field_validator("citation", mode="before")
    @classmethod
    def _citation(cls, value: object) -> str | None:
        return to_optional_string(value, "key_fact.citation")


class AIAnalysisModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str
    sentiment: Literal["bullish", "bearish", "neutral"]
    sentiment_score: float
    impact_level: Literal["high", "medium", "low"]
    key_event: str | None = None
    reasoning: str
    key_facts: list[KeyFactModel] = Field(default_factory=list)

    @field_validator("summary", "reasoning", mode="before")
    @classmethod
    def _text(cls, value: object) -> str:
        return to_string(value, "analysis text")

    @field_validator("sentiment", mode="before")
    @classmethod
    def _sentiment(cls, value: object) -> str:
        return symbol(value, "analysis.sentiment", SENTIMENT_MAP)

    @field_validator("sentiment_score", mode="before")
    @classmethod
    def _sentiment_score(cls, value: object) -> float:
        return to_number(value, "analysis.sentiment_score")

    @field_validator("impact_level", mode="before")
    @classmethod
    def _impact(cls, value: object) -> str:
        return symbol(value, "analysis.impact_level", IMPACT_MAP)

    @field_validator("key_event", mode="before")
    @classmethod
    def _key_event(cls, value: object) -> str | None:
        return to_optional_string(value, "analysis.key_event")


class FinancialNewsItemModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    url: str
    published_at: str | None = None
    fetched_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    title: str
    snippet: str
    full_content: str | None = None
    content_id: str | None = None
    source: SourceInfoModel
    related_tickers: list[FinancialEntityModel] = Field(default_factory=list)
    categories: list[
        Literal[
            "general",
            "corporate_event",
            "financials",
            "trusted_news",
            "analyst_opinion",
            "bullish",
            "bearish",
        ]
    ] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    analysis: AIAnalysisModel | None = None

    @field_validator(
        "id",
        "url",
        "fetched_at",
        "title",
        "snippet",
        "full_content",
        "content_id",
        "published_at",
        mode="before",
    )
    @classmethod
    def _optional_string_fields(cls, value: object) -> str | None:
        return to_optional_string(value, "news item string field")

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise TypeError("news item.tags must be a list")
        return [to_string(item, "news item.tags[]") for item in value]

    @field_validator("categories", mode="before")
    @classmethod
    def _categories(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise TypeError("news item.categories must be a list")
        return [symbol(item, "news item.categories[]", CATEGORY_MAP) for item in value]


class NewsArtifactModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticker: str
    news_items: list[FinancialNewsItemModel]
    overall_sentiment: Literal["bullish", "bearish", "neutral"]
    sentiment_score: float
    key_themes: list[str]

    @field_validator("ticker", mode="before")
    @classmethod
    def _ticker(cls, value: object) -> str:
        return to_string(value, "news artifact.ticker")

    @field_validator("overall_sentiment", mode="before")
    @classmethod
    def _overall_sentiment(cls, value: object) -> str:
        return symbol(value, "news artifact.overall_sentiment", SENTIMENT_MAP)

    @field_validator("sentiment_score", mode="before")
    @classmethod
    def _sentiment_score(cls, value: object) -> float:
        return to_number(value, "news artifact.sentiment_score")

    @field_validator("key_themes", mode="before")
    @classmethod
    def _themes(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise TypeError("news artifact.key_themes must be a list")
        return [to_string(item, "news artifact.key_themes[]") for item in value]


def parse_news_artifact_model(value: object) -> JSONObject:
    return validate_and_dump(
        NewsArtifactModel,
        value,
        "news artifact",
        exclude_none=True,
    )
