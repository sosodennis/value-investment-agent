from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar, cast

from pydantic import BaseModel, ValidationError

from src.agents.debate.interface.contracts import (
    DebateArtifactModel,
)
from src.agents.fundamental.interface.contracts import parse_fundamental_artifact_model
from src.agents.news.interface.contracts import (
    NewsArtifactModel,
    parse_news_artifact_model,
)
from src.agents.technical.interface.contracts import (
    TechnicalArtifactModel,
    parse_technical_artifact_model,
)
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
from src.common.types import JSONObject
from src.interface.artifact_api_models import (
    DebateFactsArtifactData,
    FinancialReportsArtifactData,
    NewsArticleArtifactData,
    NewsItemsListArtifactData,
    NewsSelectionArtifactData,
    PriceSeriesArtifactData,
    SearchResultsArtifactData,
    TechnicalChartArtifactData,
)

_ModelT = TypeVar("_ModelT", bound=BaseModel)


@dataclass(frozen=True)
class ArtifactContractSpec:
    kind: str
    model: type[BaseModel]
    dump_exclude_none: bool = False


_ARTIFACT_MODEL_SPECS: dict[str, ArtifactContractSpec] = {
    ARTIFACT_KIND_FINANCIAL_REPORTS: ArtifactContractSpec(
        kind=ARTIFACT_KIND_FINANCIAL_REPORTS,
        model=FinancialReportsArtifactData,
    ),
    ARTIFACT_KIND_PRICE_SERIES: ArtifactContractSpec(
        kind=ARTIFACT_KIND_PRICE_SERIES,
        model=PriceSeriesArtifactData,
    ),
    ARTIFACT_KIND_TA_CHART_DATA: ArtifactContractSpec(
        kind=ARTIFACT_KIND_TA_CHART_DATA,
        model=TechnicalChartArtifactData,
    ),
    ARTIFACT_KIND_TA_FULL_REPORT: ArtifactContractSpec(
        kind=ARTIFACT_KIND_TA_FULL_REPORT,
        model=TechnicalArtifactModel,
    ),
    ARTIFACT_KIND_SEARCH_RESULTS: ArtifactContractSpec(
        kind=ARTIFACT_KIND_SEARCH_RESULTS,
        model=SearchResultsArtifactData,
    ),
    ARTIFACT_KIND_NEWS_SELECTION: ArtifactContractSpec(
        kind=ARTIFACT_KIND_NEWS_SELECTION,
        model=NewsSelectionArtifactData,
    ),
    ARTIFACT_KIND_NEWS_ARTICLE: ArtifactContractSpec(
        kind=ARTIFACT_KIND_NEWS_ARTICLE,
        model=NewsArticleArtifactData,
    ),
    ARTIFACT_KIND_NEWS_ITEMS_LIST: ArtifactContractSpec(
        kind=ARTIFACT_KIND_NEWS_ITEMS_LIST,
        model=NewsItemsListArtifactData,
    ),
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT: ArtifactContractSpec(
        kind=ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
        model=NewsArtifactModel,
    ),
    ARTIFACT_KIND_DEBATE_FACTS: ArtifactContractSpec(
        kind=ARTIFACT_KIND_DEBATE_FACTS,
        model=DebateFactsArtifactData,
    ),
    ARTIFACT_KIND_DEBATE_FINAL_REPORT: ArtifactContractSpec(
        kind=ARTIFACT_KIND_DEBATE_FINAL_REPORT,
        model=DebateArtifactModel,
        dump_exclude_none=True,
    ),
}


def _canonicalize_financial_reports_payload(value: object) -> JSONObject:
    if isinstance(value, dict):
        full_report_keys = {
            "ticker",
            "model_type",
            "company_name",
            "sector",
            "industry",
            "reasoning",
            "status",
        }
        if any(key in value for key in full_report_keys):
            return parse_fundamental_artifact_model(value)
    return parse_artifact_data_json(
        ARTIFACT_KIND_FINANCIAL_REPORTS,
        value,
        context="financial_reports canonicalization",
    )


_CANONICALIZERS_BY_KIND: dict[str, Callable[[object], JSONObject]] = {
    ARTIFACT_KIND_FINANCIAL_REPORTS: _canonicalize_financial_reports_payload,
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT: parse_news_artifact_model,
    ARTIFACT_KIND_TA_FULL_REPORT: parse_technical_artifact_model,
}

_TECHNICAL_DEBATE_KINDS = frozenset(
    {
        ARTIFACT_KIND_TA_FULL_REPORT,
        ARTIFACT_KIND_TA_CHART_DATA,
        ARTIFACT_KIND_PRICE_SERIES,
    }
)

_NEWS_DEBATE_KINDS = frozenset(
    {
        ARTIFACT_KIND_NEWS_ITEMS_LIST,
        ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    }
)


def parse_artifact_data_model(
    kind: str,
    value: object,
    *,
    context: str,
) -> BaseModel:
    spec = _ARTIFACT_MODEL_SPECS.get(kind)
    if spec is None:
        raise TypeError(f"{context} has unsupported artifact kind: {kind!r}")
    try:
        return spec.model.model_validate(value)
    except ValidationError as exc:
        raise TypeError(f"{context} validation failed: {exc}") from exc


def parse_artifact_data_model_as(
    kind: str,
    value: object,
    *,
    model: type[_ModelT],
    context: str,
) -> _ModelT:
    parsed = parse_artifact_data_model(kind, value, context=context)
    if not isinstance(parsed, model):
        raise TypeError(
            f"{context} parsed model type mismatch: got {type(parsed)!r}, expected {model!r}"
        )
    return parsed


def parse_artifact_data_json(
    kind: str,
    value: object,
    *,
    context: str,
) -> JSONObject:
    spec = _ARTIFACT_MODEL_SPECS.get(kind)
    if spec is None:
        raise TypeError(f"{context} has unsupported artifact kind: {kind!r}")
    try:
        parsed = spec.model.model_validate(value)
    except ValidationError as exc:
        raise TypeError(f"{context} validation failed: {exc}") from exc

    dumped = parsed.model_dump(mode="json", exclude_none=spec.dump_exclude_none)
    if not isinstance(dumped, dict):
        raise TypeError(f"{context} must serialize to object")
    return cast(JSONObject, dumped)


def canonicalize_artifact_data_by_kind(
    kind: str, value: object, *, context: str = "artifact data"
) -> JSONObject:
    canonicalizer = _CANONICALIZERS_BY_KIND.get(kind)
    if canonicalizer is not None:
        try:
            return canonicalizer(value)
        except TypeError as exc:
            raise TypeError(f"{context} canonicalization failed: {exc}") from exc
    return parse_artifact_data_json(kind, value, context=context)


def parse_technical_debate_payload(
    kind: str,
    value: object,
    *,
    context: str,
) -> JSONObject:
    if kind not in _TECHNICAL_DEBATE_KINDS:
        raise TypeError(
            f"{context} kind {kind!r} is not supported for technical debate payload"
        )
    return parse_artifact_data_json(kind, value, context=context)


def parse_news_items_for_debate(
    kind: str,
    value: object,
    *,
    context: str,
) -> list[JSONObject]:
    if kind not in _NEWS_DEBATE_KINDS:
        raise TypeError(
            f"{context} kind {kind!r} is not supported for news debate payload"
        )

    if kind == ARTIFACT_KIND_NEWS_ITEMS_LIST:
        parsed = parse_artifact_data_model_as(
            kind,
            value,
            model=NewsItemsListArtifactData,
            context=context,
        )
        return cast(
            list[JSONObject],
            [item.model_dump(mode="json") for item in parsed.news_items],
        )

    payload = parse_artifact_data_json(kind, value, context=context)
    news_items = payload.get("news_items")
    if not isinstance(news_items, list):
        raise TypeError(f"{context} missing news_items list")
    return cast(list[JSONObject], news_items)
