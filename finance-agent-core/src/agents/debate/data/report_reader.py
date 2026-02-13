from __future__ import annotations

from dataclasses import dataclass

from src.common.contracts import (
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_NEWS_ITEMS_LIST,
    ARTIFACT_KIND_PRICE_SERIES,
    ARTIFACT_KIND_TA_CHART_DATA,
    ARTIFACT_KIND_TA_FULL_REPORT,
)
from src.common.types import JSONObject
from src.interface.artifact_api_models import FinancialReportsArtifactData
from src.interface.artifact_contract_registry import (
    parse_artifact_data_model_as,
    parse_news_items_for_debate,
    parse_technical_debate_payload,
)
from src.services.artifact_manager import artifact_manager


@dataclass(frozen=True)
class DebateSourceData:
    financial_reports: list[JSONObject]
    news_items: list[JSONObject]
    technical_payload: JSONObject | None


async def _load_financial_reports(artifact_id: str | None) -> list[JSONObject]:
    if not isinstance(artifact_id, str):
        return []
    data = await artifact_manager.get_artifact_data(
        artifact_id, expected_kind=ARTIFACT_KIND_FINANCIAL_REPORTS
    )
    if data is None:
        return []
    payload = parse_artifact_data_model_as(
        ARTIFACT_KIND_FINANCIAL_REPORTS,
        data,
        model=FinancialReportsArtifactData,
        context=f"artifact {artifact_id} {ARTIFACT_KIND_FINANCIAL_REPORTS}",
    )
    return payload.financial_reports


async def _load_news_items(artifact_id: str | None) -> list[JSONObject]:
    if not isinstance(artifact_id, str):
        return []
    envelope = await artifact_manager.get_artifact_envelope(artifact_id)
    if envelope is None:
        return []
    if envelope.kind not in {
        ARTIFACT_KIND_NEWS_ITEMS_LIST,
        ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    }:
        return []
    return parse_news_items_for_debate(
        envelope.kind,
        envelope.data,
        context=f"artifact {artifact_id} {envelope.kind}",
    )


async def _load_technical_payload(artifact_id: str | None) -> JSONObject | None:
    if not isinstance(artifact_id, str):
        return None
    envelope = await artifact_manager.get_artifact_envelope(artifact_id)
    if envelope is None:
        return None
    if envelope.kind not in {
        ARTIFACT_KIND_TA_FULL_REPORT,
        ARTIFACT_KIND_TA_CHART_DATA,
        ARTIFACT_KIND_PRICE_SERIES,
    }:
        return None
    return parse_technical_debate_payload(
        envelope.kind,
        envelope.data,
        context=f"artifact {artifact_id} {envelope.kind}",
    )


async def load_debate_source_data(
    *,
    financial_reports_artifact_id: str | None,
    news_artifact_id: str | None,
    technical_artifact_id: str | None,
) -> DebateSourceData:
    financial_reports = await _load_financial_reports(financial_reports_artifact_id)
    news_items = await _load_news_items(news_artifact_id)
    technical_payload = await _load_technical_payload(technical_artifact_id)

    return DebateSourceData(
        financial_reports=financial_reports,
        news_items=news_items,
        technical_payload=technical_payload,
    )
