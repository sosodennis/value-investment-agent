from __future__ import annotations

from src.common.contracts import (
    ARTIFACT_KIND_DEBATE_FINAL_REPORT,
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_TA_FULL_REPORT,
)
from src.common.types import JSONObject
from src.interface.artifact_api_models import FinancialReportsArtifactData
from src.interface.artifact_contract_registry import (
    canonicalize_artifact_data_by_kind,
    parse_artifact_data_model_as,
)


def normalize_financial_reports(value: object, context: str) -> list[JSONObject]:
    try:
        parsed = parse_artifact_data_model_as(
            ARTIFACT_KIND_FINANCIAL_REPORTS,
            {"financial_reports": value},
            model=FinancialReportsArtifactData,
            context=context,
        )
    except TypeError as exc:
        raise TypeError(f"{context}: {exc}") from exc
    dumped = parsed.model_dump(mode="json")
    reports = dumped.get("financial_reports")
    if not isinstance(reports, list):
        raise TypeError(f"{context}: financial_reports must serialize to list")
    return reports


def canonicalize_fundamental_artifact_data(value: object) -> JSONObject:
    return canonicalize_artifact_data_by_kind(
        ARTIFACT_KIND_FINANCIAL_REPORTS,
        value,
        context="financial_reports canonicalization",
    )


def canonicalize_news_artifact_data(value: object) -> JSONObject:
    return canonicalize_artifact_data_by_kind(
        ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
        value,
        context="news_analysis_report canonicalization",
    )


def canonicalize_debate_artifact_data(value: object) -> JSONObject:
    return canonicalize_artifact_data_by_kind(
        ARTIFACT_KIND_DEBATE_FINAL_REPORT,
        value,
        context="debate_final_report canonicalization",
    )


def canonicalize_technical_artifact_data(value: object) -> JSONObject:
    return canonicalize_artifact_data_by_kind(
        ARTIFACT_KIND_TA_FULL_REPORT,
        value,
        context="ta_full_report canonicalization",
    )
