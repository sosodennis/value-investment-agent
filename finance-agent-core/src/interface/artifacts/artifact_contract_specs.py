from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from src.agents.debate.interface.contracts import DebateArtifactModel
from src.agents.news.interface.contracts import NewsArtifactModel
from src.agents.technical.interface.contracts import TechnicalArtifactModel
from src.interface.artifacts.artifact_data_models import (
    DebateFactsArtifactData,
    FinancialReportsArtifactData,
    NewsArticleArtifactData,
    NewsItemsListArtifactData,
    NewsSelectionArtifactData,
    PriceSeriesArtifactData,
    SearchResultsArtifactData,
    TechnicalAlertsArtifactData,
    TechnicalChartArtifactData,
    TechnicalDirectionScorecardArtifactData,
    TechnicalFeaturePackArtifactData,
    TechnicalFusionReportArtifactData,
    TechnicalIndicatorSeriesArtifactData,
    TechnicalPatternPackArtifactData,
    TechnicalTimeseriesBundleArtifactData,
    TechnicalVerificationReportArtifactData,
)
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_DEBATE_FACTS,
    ARTIFACT_KIND_DEBATE_FINAL_REPORT,
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_NEWS_ARTICLE,
    ARTIFACT_KIND_NEWS_ITEMS_LIST,
    ARTIFACT_KIND_NEWS_SELECTION,
    ARTIFACT_KIND_PRICE_SERIES,
    ARTIFACT_KIND_SEARCH_RESULTS,
    ARTIFACT_KIND_TA_ALERTS,
    ARTIFACT_KIND_TA_CHART_DATA,
    ARTIFACT_KIND_TA_DIRECTION_SCORECARD,
    ARTIFACT_KIND_TA_FEATURE_PACK,
    ARTIFACT_KIND_TA_FULL_REPORT,
    ARTIFACT_KIND_TA_FUSION_REPORT,
    ARTIFACT_KIND_TA_INDICATOR_SERIES,
    ARTIFACT_KIND_TA_PATTERN_PACK,
    ARTIFACT_KIND_TA_TIMESERIES_BUNDLE,
    ARTIFACT_KIND_TA_VERIFICATION_REPORT,
)


@dataclass(frozen=True)
class ArtifactContractSpec:
    kind: str
    model: type[BaseModel]
    dump_exclude_none: bool = False


ARTIFACT_CONTRACT_SPECS: tuple[ArtifactContractSpec, ...] = (
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_FINANCIAL_REPORTS,
        model=FinancialReportsArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_PRICE_SERIES,
        model=PriceSeriesArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_TA_CHART_DATA,
        model=TechnicalChartArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_TA_INDICATOR_SERIES,
        model=TechnicalIndicatorSeriesArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_TA_ALERTS,
        model=TechnicalAlertsArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_TA_TIMESERIES_BUNDLE,
        model=TechnicalTimeseriesBundleArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_TA_FEATURE_PACK,
        model=TechnicalFeaturePackArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_TA_PATTERN_PACK,
        model=TechnicalPatternPackArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_TA_FUSION_REPORT,
        model=TechnicalFusionReportArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_TA_DIRECTION_SCORECARD,
        model=TechnicalDirectionScorecardArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_TA_VERIFICATION_REPORT,
        model=TechnicalVerificationReportArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_TA_FULL_REPORT,
        model=TechnicalArtifactModel,
        dump_exclude_none=True,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_SEARCH_RESULTS,
        model=SearchResultsArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_NEWS_SELECTION,
        model=NewsSelectionArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_NEWS_ARTICLE,
        model=NewsArticleArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_NEWS_ITEMS_LIST,
        model=NewsItemsListArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
        model=NewsArtifactModel,
        dump_exclude_none=True,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_DEBATE_FACTS,
        model=DebateFactsArtifactData,
    ),
    ArtifactContractSpec(
        kind=ARTIFACT_KIND_DEBATE_FINAL_REPORT,
        model=DebateArtifactModel,
        dump_exclude_none=True,
    ),
)


ARTIFACT_CONTRACT_SPEC_BY_KIND: dict[str, ArtifactContractSpec] = {
    spec.kind: spec for spec in ARTIFACT_CONTRACT_SPECS
}
