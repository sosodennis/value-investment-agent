from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.workflow.nodes.financial_news_research.nodes import (
    aggregator_node,
    analyst_node,
    fetch_node,
    search_node,
    selector_node,
)


@pytest.mark.asyncio
async def test_search_node_error_log():
    state = {
        "ticker": "AAPL",
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "node_statuses": {},
        "error_logs": [],
    }

    with patch(
        "src.agents.news.application.factory.news_search_multi_timeframe"
    ) as mock_search:
        mock_search.side_effect = Exception("Search API Error")

        command = await search_node(state)

        assert command.update["internal_progress"]["search_node"] == "error"
        assert command.update["node_statuses"]["financial_news_research"] == "error"
        assert len(command.update["error_logs"]) == 1
        assert "Search API Error" in command.update["error_logs"][0]["error"]
        assert command.goto == "__end__"


@pytest.mark.asyncio
async def test_selector_node_error_log():
    state = {
        "ticker": "AAPL",
        "financial_news_research": {"search_artifact_id": "art_123"},
    }

    with patch(
        "src.services.artifact_manager.artifact_manager.get_artifact_data"
    ) as mock_get:
        mock_get.return_value = {"raw_results": [], "formatted_results": ""}

        with patch("src.agents.news.application.factory.get_llm") as mock_llm:
            # Simulate LLM failure
            mock_chain = MagicMock()
            mock_chain.invoke.side_effect = Exception("LLM Timeout")
            mock_llm.return_value = mock_chain

            command = await selector_node(state)

            assert (
                command.update["node_statuses"]["financial_news_research"] == "degraded"
            )
            assert "error_logs" in command.update
            assert "Selection failed" in command.update["error_logs"][0]["error"]
            assert command.goto == "fetch_node"


@pytest.mark.asyncio
async def test_fetch_node_error_log():
    state = {
        "financial_news_research": {
            "search_artifact_id": "s1",
            "selection_artifact_id": "sel1",
        }
    }

    # We simulate an artifact store error which should now be caught
    # and added to article_errors, making the status degraded.
    with patch(
        "src.services.artifact_manager.artifact_manager.get_artifact_data"
    ) as mock_get:
        mock_get.side_effect = Exception("Artifact Store Error")

        command = await fetch_node(state)

        assert command.update["node_statuses"]["financial_news_research"] == "degraded"
        # The error message comes from the new catch block
        assert (
            "Failed to retrieve search/selection artifacts"
            in command.update["error_logs"][0]["error"]
        )
        assert command.goto == "analyst_node"


@pytest.mark.asyncio
async def test_analyst_node_error_log():
    state = {
        "ticker": "AAPL",
        "financial_news_research": {"news_items_artifact_id": "n1"},
    }

    async def mock_get_artifact_data(_artifact_id, expected_kind=None):
        if expected_kind == "news_items_list":
            return {"news_items": [{"title": "T1", "link": "L1"}]}
        return None

    with patch(
        "src.services.artifact_manager.artifact_manager.get_artifact_data",
        side_effect=mock_get_artifact_data,
    ):
        with patch("src.agents.news.application.factory.get_llm") as mock_llm:
            with patch(
                "src.agents.news.application.factory.get_finbert_analyzer"
            ) as mock_finbert:
                # Ensure finbert doesn't crash test
                mock_finbert.return_value.is_available.return_value = False

                # Simulate chain failure
                # We need to mock the object returned by llm.with_structured_output
                mock_struct_llm = MagicMock()
                error = Exception("Analysis Error")
                mock_struct_llm.invoke.side_effect = error
                mock_struct_llm.batch.side_effect = error
                mock_struct_llm.stream.side_effect = error
                mock_struct_llm.side_effect = error  # Cover __call__

                mock_llm_instance = MagicMock()
                mock_llm_instance.with_structured_output.return_value = mock_struct_llm

                mock_llm.return_value = mock_llm_instance

                command = await analyst_node(state)

                assert (
                    command.update["node_statuses"]["financial_news_research"]
                    == "degraded"
                )
                assert "Failed to analyze" in command.update["error_logs"][0]["error"]
                assert command.goto == "aggregator_node"


@pytest.mark.asyncio
async def test_aggregator_node_payload_build_failure_returns_error_update() -> None:
    state = {
        "ticker": "AAPL",
        "financial_news_research": {"news_items_artifact_id": "news-items-1"},
    }

    with (
        patch(
            "src.agents.news.application.factory.news_workflow_runner.orchestrator.port.load_news_items_data",
            new=AsyncMock(
                return_value=[
                    {
                        "id": "n1",
                        "url": "https://example.com/story",
                        "title": "Sample",
                        "snippet": "Sample",
                        "source": {
                            "name": "Reuters",
                            "domain": "reuters.com",
                            "reliability_score": 0.9,
                        },
                    }
                ]
            ),
        ),
        patch(
            "src.agents.news.application.orchestrator.parse_news_artifact_model",
            side_effect=RuntimeError("payload boom"),
        ),
    ):
        command = await aggregator_node(state)

    assert command.goto == "__end__"
    assert command.update["internal_progress"]["aggregator_node"] == "error"
    assert command.update["node_statuses"]["financial_news_research"] == "error"
    assert (
        command.update["error_logs"][0]["error_code"]
        == "NEWS_REPORT_PAYLOAD_BUILD_FAILED"
    )
