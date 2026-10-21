"""News agent request and artifact schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.shared.artifacts.news_contracts import (
    AIAnalysisModel,
    FinancialEntityModel,
    FinancialNewsItemModel,
    KeyFactModel,
    NewsArtifactModel,
    NewsSearchResultItemModel,
    SourceInfoModel,
    parse_news_artifact_model,
)


class SelectedArticleModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    priority: Literal["High", "Medium"]


class SelectorResponseModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    selected_articles: list[SelectedArticleModel] = Field(default_factory=list)


__all__ = [
    "AIAnalysisModel",
    "FinancialEntityModel",
    "FinancialNewsItemModel",
    "KeyFactModel",
    "NewsArtifactModel",
    "NewsSearchResultItemModel",
    "SourceInfoModel",
    "SelectedArticleModel",
    "SelectorResponseModel",
    "parse_news_artifact_model",
]
