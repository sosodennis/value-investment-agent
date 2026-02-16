from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from src.agents.debate.interface.contracts import EvidenceFactModel
from src.agents.fundamental.interface.contracts import FinancialReportModel
from src.agents.news.interface.contracts import (
    FinancialNewsItemModel,
    NewsSearchResultItemModel,
)


class FinancialReportsArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    financial_reports: list[FinancialReportModel]
    ticker: str | None = None
    model_type: str | None = None
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    reasoning: str | None = None
    status: Literal["done"] | None = None


class PriceSeriesArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_series: dict[str, float | None]
    volume_series: dict[str, float | None]


class TechnicalChartArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fracdiff_series: dict[str, float | None]
    z_score_series: dict[str, float | None]
    indicators: dict[str, object]


class SearchResultsArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_results: list[NewsSearchResultItemModel]
    formatted_results: str


class NewsSelectionArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_indices: list[int]


class NewsArticleArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_text: str
    title: str | None = None
    url: str | None = None


class NewsItemsListArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    news_items: list[FinancialNewsItemModel]


class DebateFactsArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    facts: list[EvidenceFactModel]
    facts_hash: str
    generated_at: str
