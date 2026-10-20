"""Compatibility exports for the shared news artifact contract."""

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

__all__ = [
    "AIAnalysisModel",
    "FinancialEntityModel",
    "FinancialNewsItemModel",
    "KeyFactModel",
    "NewsArtifactModel",
    "NewsSearchResultItemModel",
    "SourceInfoModel",
    "parse_news_artifact_model",
]
