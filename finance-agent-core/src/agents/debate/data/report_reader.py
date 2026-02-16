from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from src.agents.debate.application.dto import DebateSourceData
from src.agents.news.interface.contracts import NewsArtifactModel
from src.interface.artifacts.artifact_contract_registry import (
    parse_artifact_data_json,
    parse_artifact_data_model_as,
)
from src.interface.artifacts.artifact_data_models import FinancialReportsArtifactData
from src.services.artifact_manager import artifact_manager
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_TA_FULL_REPORT,
)
from src.shared.kernel.types import JSONObject


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
    dumped = payload.model_dump(mode="json", exclude_none=True)
    financial_reports = dumped.get("financial_reports")
    if not isinstance(financial_reports, list):
        raise TypeError(
            f"artifact {artifact_id} {ARTIFACT_KIND_FINANCIAL_REPORTS} missing financial_reports list"
        )
    return cast(list[JSONObject], financial_reports)


async def _load_news_items(artifact_id: str | None) -> list[JSONObject]:
    if not isinstance(artifact_id, str):
        return []
    data = await artifact_manager.get_artifact_data(
        artifact_id, expected_kind=ARTIFACT_KIND_NEWS_ANALYSIS_REPORT
    )
    if data is None:
        return []
    payload = parse_artifact_data_model_as(
        ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
        data,
        model=NewsArtifactModel,
        context=f"artifact {artifact_id} {ARTIFACT_KIND_NEWS_ANALYSIS_REPORT}",
    )
    dumped = payload.model_dump(mode="json", exclude_none=True)
    news_items = dumped.get("news_items")
    if not isinstance(news_items, list):
        raise TypeError(
            f"artifact {artifact_id} {ARTIFACT_KIND_NEWS_ANALYSIS_REPORT} missing news_items list"
        )
    return cast(list[JSONObject], news_items)


async def _load_technical_payload(artifact_id: str | None) -> JSONObject | None:
    if not isinstance(artifact_id, str):
        return None
    data = await artifact_manager.get_artifact_data(
        artifact_id, expected_kind=ARTIFACT_KIND_TA_FULL_REPORT
    )
    if data is None:
        return None
    return parse_artifact_data_json(
        ARTIFACT_KIND_TA_FULL_REPORT,
        data,
        context=f"artifact {artifact_id} {ARTIFACT_KIND_TA_FULL_REPORT}",
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


@dataclass(frozen=True)
class ArtifactDebateSourceReader:
    async def load_debate_source_data(
        self,
        *,
        financial_reports_artifact_id: str | None,
        news_artifact_id: str | None,
        technical_artifact_id: str | None,
    ) -> DebateSourceData:
        return await load_debate_source_data(
            financial_reports_artifact_id=financial_reports_artifact_id,
            news_artifact_id=news_artifact_id,
            technical_artifact_id=technical_artifact_id,
        )


debate_source_reader = ArtifactDebateSourceReader()
