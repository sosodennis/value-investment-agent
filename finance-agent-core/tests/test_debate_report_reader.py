from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.agents.debate.infrastructure.artifacts.debate_source_reader_repository import (
    DebateSourceReaderRepository,
    build_default_debate_source_reader_repository,
)
from src.agents.technical.interface.contracts import parse_technical_artifact_model
from src.artifacts.public import (
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_TA_FULL_REPORT,
)
from src.shared.artifacts.artifact_data_models import FinancialReportsArtifactData
from src.shared.artifacts.news_contracts import NewsArtifactModel
from src.shared.kernel.types import JSONObject


def _build_repository(
    *,
    financial: FinancialReportsArtifactData | None,
    news: NewsArtifactModel | None,
    technical: JSONObject | None,
) -> DebateSourceReaderRepository:
    financial_port = AsyncMock()
    financial_port.load.return_value = financial
    news_port = AsyncMock()
    news_port.load.return_value = news
    technical_port = AsyncMock()
    technical_port.load_json.return_value = technical
    return DebateSourceReaderRepository(
        financial_reports_port=financial_port,
        news_report_port=news_port,
        technical_report_port=technical_port,
    )


def test_source_reader_handles_valid_empty_news_and_preserves_other_sources() -> None:
    financial = FinancialReportsArtifactData.model_validate(
        {
            "ticker": "AAPL",
            "model_type": "saas",
            "company_name": None,
            "sector": None,
            "industry": None,
            "reasoning": None,
            "status": "done",
            "financial_reports": [
                {
                    "industry_type": "General",
                    "base": {
                        "fiscal_year": {"value": "2024"},
                        "fiscal_period": {"value": "FY"},
                    },
                }
            ],
        }
    )
    news = NewsArtifactModel.model_validate(
        {
            "ticker": "AAPL",
            "overall_sentiment": "neutral",
            "sentiment_score": 0.0,
            "key_themes": [],
            "news_items": [],
        }
    )
    technical = parse_technical_artifact_model(
        {
            "schema_version": "2.0",
            "ticker": "AAPL",
            "as_of": "2026-01-01T00:00:00+00:00",
            "direction": "bullish",
            "risk_level": "medium",
            "confidence": 0.55,
            "summary_tags": ["mean-reversion"],
            "diagnostics": {
                "is_degraded": True,
                "degraded_reasons": ["low_liquidity"],
            },
            "artifact_refs": {
                "chart_data_id": "chart-1",
                "timeseries_bundle_id": "bundle-1",
                "feature_pack_id": "feature-1",
            },
        }
    )
    repository = _build_repository(
        financial=financial,
        news=news,
        technical=technical,
    )

    source = asyncio.run(
        repository.load_debate_source_data(
            financial_reports_artifact_id="fa-1",
            news_artifact_id="news-1",
            technical_artifact_id="ta-1",
        )
    )

    assert len(source.financial_reports) == 1
    assert source.news_items == []
    assert source.technical_payload is not None
    assert source.technical_payload["ticker"] == "AAPL"
    assert source.is_degraded is True
    assert [issue.reason_code for issue in source.load_issues] == ["news:empty_payload"]


def test_source_reader_distinguishes_missing_ids_from_missing_artifacts() -> None:
    repository = _build_repository(financial=None, news=None, technical=None)

    missing_ids = asyncio.run(
        repository.load_debate_source_data(
            financial_reports_artifact_id=None,
            news_artifact_id=None,
            technical_artifact_id=None,
        )
    )
    assert [issue.reason_code for issue in missing_ids.load_issues] == [
        "financial_reports:missing_artifact_id",
        "news:missing_artifact_id",
        "technical_analysis:missing_artifact_id",
    ]

    missing_artifacts = asyncio.run(
        repository.load_debate_source_data(
            financial_reports_artifact_id="fa-missing",
            news_artifact_id="news-missing",
            technical_artifact_id="ta-missing",
        )
    )
    assert [issue.reason_code for issue in missing_artifacts.load_issues] == [
        "financial_reports:artifact_not_found",
        "news:artifact_not_found",
        "technical_analysis:artifact_not_found",
    ]


def test_default_reader_uses_typed_ports_for_canonical_kinds() -> None:
    repository = build_default_debate_source_reader_repository()

    assert repository.financial_reports_port.kind == ARTIFACT_KIND_FINANCIAL_REPORTS
    assert repository.news_report_port.kind == ARTIFACT_KIND_NEWS_ANALYSIS_REPORT
    assert repository.technical_report_port.kind == ARTIFACT_KIND_TA_FULL_REPORT
