import asyncio
from unittest.mock import AsyncMock, patch

from src.agents.debate.infrastructure.artifacts.debate_source_reader_repository import (
    load_debate_source_data,
)
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_TA_FULL_REPORT,
)


def test_load_debate_source_data_reads_all_three_sources() -> None:
    with (
        patch(
            "src.agents.debate.infrastructure.artifacts.debate_source_reader_repository.artifact_manager.get_artifact_data",
            new=AsyncMock(
                side_effect=[
                    {
                        "financial_reports": [
                            {
                                "industry_type": "General",
                                "base": {
                                    "fiscal_year": {"value": "2024"},
                                    "fiscal_period": {"value": "FY"},
                                },
                            }
                        ]
                    },
                    {
                        "ticker": "AAPL",
                        "overall_sentiment": "bullish",
                        "sentiment_score": 0.7,
                        "key_themes": ["AI"],
                        "news_items": [],
                    },
                    {
                        "ticker": "AAPL",
                        "schema_version": "2.0",
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
                    },
                ]
            ),
        ),
    ):
        source = asyncio.run(
            load_debate_source_data(
                financial_reports_artifact_id="fa-1",
                news_artifact_id="news-1",
                technical_artifact_id="ta-1",
            )
        )

    assert len(source.financial_reports) == 1
    assert isinstance(source.financial_reports[0], dict)
    assert source.news_items == []
    assert source.technical_payload is not None
    assert source.technical_payload.get("ticker") == "AAPL"
    assert source.is_degraded is True
    assert [issue.reason_code for issue in source.load_issues] == ["news:empty_payload"]


def test_load_debate_source_data_handles_missing_ids() -> None:
    source = asyncio.run(
        load_debate_source_data(
            financial_reports_artifact_id=None,
            news_artifact_id=None,
            technical_artifact_id=None,
        )
    )
    assert source.financial_reports == []
    assert source.news_items == []
    assert source.technical_payload is None
    assert source.is_degraded is True
    assert [issue.reason_code for issue in source.load_issues] == [
        "financial_reports:missing_artifact_id",
        "news:missing_artifact_id",
        "technical_analysis:missing_artifact_id",
    ]


def test_load_debate_source_data_uses_expected_kinds() -> None:
    with patch(
        "src.agents.debate.infrastructure.artifacts.debate_source_reader_repository.artifact_manager.get_artifact_data",
        new=AsyncMock(side_effect=[None, None, None]),
    ) as mocked_get_artifact_data:
        source = asyncio.run(
            load_debate_source_data(
                financial_reports_artifact_id="fa-1",
                news_artifact_id="news-1",
                technical_artifact_id="ta-1",
            )
        )

    expected_calls = [
        ("fa-1", ARTIFACT_KIND_FINANCIAL_REPORTS),
        ("news-1", ARTIFACT_KIND_NEWS_ANALYSIS_REPORT),
        ("ta-1", ARTIFACT_KIND_TA_FULL_REPORT),
    ]
    assert mocked_get_artifact_data.await_count == 3
    for awaited_call, (artifact_id, expected_kind) in zip(
        mocked_get_artifact_data.await_args_list, expected_calls, strict=True
    ):
        assert awaited_call.args[0] == artifact_id
        assert awaited_call.kwargs["expected_kind"] == expected_kind

    assert [issue.reason_code for issue in source.load_issues] == [
        "financial_reports:artifact_not_found",
        "news:artifact_not_found",
        "technical_analysis:artifact_not_found",
    ]
