import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.agents.debate.data.report_reader import load_debate_source_data
from src.common.contracts import (
    ARTIFACT_KIND_NEWS_ITEMS_LIST,
    ARTIFACT_KIND_TA_CHART_DATA,
)


def test_load_debate_source_data_reads_all_three_sources() -> None:
    with (
        patch(
            "src.agents.debate.data.report_reader.artifact_manager.get_artifact_data",
            new=AsyncMock(
                return_value={
                    "financial_reports": [{"base": {"fiscal_year": {"value": "2024"}}}]
                }
            ),
        ),
        patch(
            "src.agents.debate.data.report_reader.parse_artifact_data_model_as",
            return_value=SimpleNamespace(
                financial_reports=[{"base": {"fiscal_year": {"value": "2024"}}}]
            ),
        ),
        patch(
            "src.agents.debate.data.report_reader.artifact_manager.get_artifact_envelope",
            new=AsyncMock(
                side_effect=[
                    SimpleNamespace(
                        kind=ARTIFACT_KIND_NEWS_ITEMS_LIST,
                        data={"news_items": [{"title": "n1"}]},
                    ),
                    SimpleNamespace(
                        kind=ARTIFACT_KIND_TA_CHART_DATA,
                        data={
                            "fracdiff_series": {"2026-01-01": 0.1},
                            "z_score_series": {"2026-01-01": 1.2},
                            "indicators": {},
                        },
                    ),
                ]
            ),
        ),
        patch(
            "src.agents.debate.data.report_reader.parse_news_items_for_debate",
            return_value=[{"title": "n1"}],
        ),
        patch(
            "src.agents.debate.data.report_reader.parse_technical_debate_payload",
            return_value={"signal_state": {"z_score": 1.2}},
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
    assert len(source.news_items) == 1
    assert source.technical_payload is not None


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
