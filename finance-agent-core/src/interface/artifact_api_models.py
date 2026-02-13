from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from src.agents.debate.interface.contracts import (
    DebateArtifactModel,
    EvidenceFactModel,
)
from src.agents.fundamental.interface.contracts import FinancialReportModel
from src.agents.news.interface.contracts import NewsArtifactModel
from src.agents.technical.interface.contracts import TechnicalArtifactModel
from src.common.contracts import (
    ARTIFACT_KIND_DEBATE_FACTS,
    ARTIFACT_KIND_DEBATE_FINAL_REPORT,
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_NEWS_ARTICLE,
    ARTIFACT_KIND_NEWS_ITEMS_LIST,
    ARTIFACT_KIND_NEWS_SELECTION,
    ARTIFACT_KIND_PRICE_SERIES,
    ARTIFACT_KIND_SEARCH_RESULTS,
    ARTIFACT_KIND_TA_CHART_DATA,
    ARTIFACT_KIND_TA_FULL_REPORT,
)


class ArtifactEnvelopeBase(BaseModel):
    version: Literal["v1"]
    produced_by: str
    created_at: str


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

    raw_results: list[dict[str, object]]
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

    news_items: list[dict[str, object]]


class DebateFactsArtifactData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str
    facts: list[EvidenceFactModel]
    facts_hash: str
    generated_at: str


class FinancialReportsArtifactEnvelope(ArtifactEnvelopeBase):
    kind: Literal[ARTIFACT_KIND_FINANCIAL_REPORTS]
    data: FinancialReportsArtifactData


class PriceSeriesArtifactEnvelope(ArtifactEnvelopeBase):
    kind: Literal[ARTIFACT_KIND_PRICE_SERIES]
    data: PriceSeriesArtifactData


class TechnicalChartArtifactEnvelope(ArtifactEnvelopeBase):
    kind: Literal[ARTIFACT_KIND_TA_CHART_DATA]
    data: TechnicalChartArtifactData


class TechnicalReportArtifactEnvelope(ArtifactEnvelopeBase):
    kind: Literal[ARTIFACT_KIND_TA_FULL_REPORT]
    data: TechnicalArtifactModel


class SearchResultsArtifactEnvelope(ArtifactEnvelopeBase):
    kind: Literal[ARTIFACT_KIND_SEARCH_RESULTS]
    data: SearchResultsArtifactData


class NewsSelectionArtifactEnvelope(ArtifactEnvelopeBase):
    kind: Literal[ARTIFACT_KIND_NEWS_SELECTION]
    data: NewsSelectionArtifactData


class NewsArticleArtifactEnvelope(ArtifactEnvelopeBase):
    kind: Literal[ARTIFACT_KIND_NEWS_ARTICLE]
    data: NewsArticleArtifactData


class NewsItemsListArtifactEnvelope(ArtifactEnvelopeBase):
    kind: Literal[ARTIFACT_KIND_NEWS_ITEMS_LIST]
    data: NewsItemsListArtifactData


class NewsReportArtifactEnvelope(ArtifactEnvelopeBase):
    kind: Literal[ARTIFACT_KIND_NEWS_ANALYSIS_REPORT]
    data: NewsArtifactModel


class DebateFactsArtifactEnvelope(ArtifactEnvelopeBase):
    kind: Literal[ARTIFACT_KIND_DEBATE_FACTS]
    data: DebateFactsArtifactData


class DebateReportArtifactEnvelope(ArtifactEnvelopeBase):
    kind: Literal[ARTIFACT_KIND_DEBATE_FINAL_REPORT]
    data: DebateArtifactModel


ArtifactApiResponse = Annotated[
    FinancialReportsArtifactEnvelope
    | PriceSeriesArtifactEnvelope
    | TechnicalChartArtifactEnvelope
    | TechnicalReportArtifactEnvelope
    | SearchResultsArtifactEnvelope
    | NewsSelectionArtifactEnvelope
    | NewsArticleArtifactEnvelope
    | NewsItemsListArtifactEnvelope
    | NewsReportArtifactEnvelope
    | DebateFactsArtifactEnvelope
    | DebateReportArtifactEnvelope,
    Field(discriminator="kind"),
]

_ARTIFACT_API_RESPONSE_ADAPTER = TypeAdapter(ArtifactApiResponse)


def validate_artifact_api_response(
    value: object, *, context: str = "artifact response"
) -> ArtifactApiResponse:
    try:
        return _ARTIFACT_API_RESPONSE_ADAPTER.validate_python(value)
    except ValidationError as exc:
        raise TypeError(f"{context} validation failed: {exc}") from exc
