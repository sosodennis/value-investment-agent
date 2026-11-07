from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from src.agents.debate.infrastructure.artifacts.debate_source_reader_repository import (
    DebateSourceReaderRepository,
    build_default_debate_source_reader_repository,
)
from src.agents.technical.interface.contracts import parse_technical_artifact_model
from src.artifacts.public import (
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_TA_FULL_REPORT,
)
from src.shared.artifacts.news_contracts import NewsArtifactModel
from src.shared.kernel.types import JSONObject


def _build_repository(
    *,
    news: NewsArtifactModel | None,
    technical: JSONObject | None,
) -> DebateSourceReaderRepository:
    news_port = AsyncMock()
    news_port.load.return_value = news
    technical_port = AsyncMock()
    technical_port.load_json.return_value = technical
    return DebateSourceReaderRepository(
        news_report_port=news_port,
        technical_report_port=technical_port,
    )


def test_source_reader_keeps_financial_facts_unavailable_until_service_snapshot() -> (
    None
):
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
    repository = _build_repository(news=news, technical=technical)

    source = asyncio.run(
        repository.load_debate_source_data(
            news_artifact_id="news-1",
            technical_artifact_id="ta-1",
        )
    )

    assert source.financial_reports == []
    assert source.valuation_preview is None
    assert source.news_items == []
    assert source.technical_payload is not None
    assert source.technical_payload["ticker"] == "AAPL"
    assert [issue.reason_code for issue in source.load_issues] == [
        "financial_reports:service_snapshot_unavailable",
        "news:empty_payload",
    ]


def test_source_reader_distinguishes_missing_ids_from_missing_artifacts() -> None:
    repository = _build_repository(news=None, technical=None)

    missing_ids = asyncio.run(
        repository.load_debate_source_data(
            news_artifact_id=None,
            technical_artifact_id=None,
        )
    )
    assert [issue.reason_code for issue in missing_ids.load_issues] == [
        "financial_reports:service_snapshot_unavailable",
        "news:missing_artifact_id",
        "technical_analysis:missing_artifact_id",
    ]

    missing_artifacts = asyncio.run(
        repository.load_debate_source_data(
            news_artifact_id="news-missing",
            technical_artifact_id="ta-missing",
        )
    )
    assert [issue.reason_code for issue in missing_artifacts.load_issues] == [
        "financial_reports:service_snapshot_unavailable",
        "news:artifact_not_found",
        "technical_analysis:artifact_not_found",
    ]


def test_default_reader_uses_only_current_debate_source_ports() -> None:
    repository = build_default_debate_source_reader_repository()

    assert repository.news_report_port.kind == ARTIFACT_KIND_NEWS_ANALYSIS_REPORT
    assert repository.technical_report_port.kind == ARTIFACT_KIND_TA_FULL_REPORT
