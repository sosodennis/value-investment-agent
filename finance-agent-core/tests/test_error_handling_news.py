from unittest.mock import AsyncMock, patch

import pytest

from src.agents.news.application.wiring import get_news_workflow_runner
from src.agents.news.workflow.nodes import build_news_nodes
from src.model_inference.entrypoint import InferenceErrorCode, InferenceFailure

news_nodes = build_news_nodes(get_news_workflow_runner())
aggregator_node = news_nodes["aggregator_node"]
analyst_node = news_nodes["analyst_node"]
fetch_node = news_nodes["fetch_node"]
search_node = news_nodes["search_node"]
selector_node = news_nodes["selector_node"]


@pytest.mark.asyncio
async def test_search_node_error_log():
    state = {
        "ticker": "AAPL",
        "intent_extraction": {"resolved_ticker": "AAPL"},
        "error_logs": [],
    }

    with patch(
        "src.agents.news.application.wiring.news_search_multi_timeframe"
    ) as mock_search:
        mock_search.side_effect = Exception("Search API Error")

        command = await search_node(state)

        assert command.update["internal_progress"]["search_node"] == "error"
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
        with patch(
            "src.services.artifact_manager.artifact_manager.save_artifact",
            new=AsyncMock(return_value="selection-artifact-1"),
        ):
            provider = get_news_workflow_runner().deps.llm_provider
            with patch.object(
                provider,
                "acomplete_structured",
                new=AsyncMock(side_effect=Exception("LLM Timeout")),
            ):
                command = await selector_node(state)

                assert command.update["internal_progress"]["selector_node"] == "done"
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

        assert command.update["internal_progress"]["fetch_node"] == "error"
        # The error message comes from the new catch block
        assert (
            "Failed to retrieve search/selection artifacts"
            in command.update["error_logs"][0]["error"]
        )
        assert command.goto == "__end__"


@pytest.mark.asyncio
async def test_analyst_node_error_log():
    state = {
        "ticker": "AAPL",
        "financial_news_research": {"news_items_artifact_id": "n1"},
    }

    async def mock_get_artifact_data(_artifact_id, expected_kind=None):
        if expected_kind == "news_items_list":
            return {
                "news_items": [
                    {
                        "id": "n1",
                        "url": "https://example.com/news/1",
                        "title": "T1",
                        "snippet": "S1",
                        "source": {
                            "name": "Reuters",
                            "domain": "reuters.com",
                            "reliability_score": 0.9,
                        },
                        "categories": ["general"],
                    }
                ]
            }
        return None

    with patch(
        "src.services.artifact_manager.artifact_manager.get_artifact_data",
        side_effect=mock_get_artifact_data,
    ):
        provider = get_news_workflow_runner().deps.llm_provider
        with patch.object(
            provider,
            "acomplete_structured",
            new=AsyncMock(side_effect=Exception("Analysis Error")),
        ):
            with patch.object(
                get_news_workflow_runner().deps.model_inference,
                "news_sentiment",
                new=AsyncMock(
                    side_effect=InferenceFailure(
                        code=InferenceErrorCode.UNAVAILABLE,
                        request_id="test-request",
                        retryable=True,
                    )
                ),
            ):
                command = await analyst_node(state)

                assert (
                    command.update["internal_progress"]["aggregator_node"] == "running"
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
        patch.object(
            get_news_workflow_runner().orchestrator.port,
            "load_news_items_data",
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
            "src.agents.news.application.use_cases.run_aggregator_node_use_case.parse_news_artifact_model",
            side_effect=RuntimeError("payload boom"),
        ),
    ):
        command = await aggregator_node(state)

    assert command.goto == "__end__"
    assert command.update["internal_progress"]["aggregator_node"] == "error"
    assert (
        command.update["error_logs"][0]["error_code"]
        == "NEWS_REPORT_PAYLOAD_BUILD_FAILED"
    )
