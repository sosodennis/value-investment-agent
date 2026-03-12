import logging
from unittest.mock import patch

import pytest

from src.agents.intent.application.orchestrator import _SearchCandidatesOutcome
from src.agents.intent.domain.ticker_candidate import TickerCandidate
from src.workflow.nodes.intent_extraction.nodes import (
    decision_node,
    extraction_node,
    searching_node,
)


@pytest.mark.asyncio
async def test_extraction_node_error_degraded_path():
    state = {"user_query": "Analyze Apple"}

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.intent_orchestrator.extract_intent",
        side_effect=Exception("LLM Error"),
    ):
        command = await extraction_node(state)

        assert command.goto == "clarifying"
        assert command.update["node_statuses"]["intent_extraction"] == "degraded"
        assert (
            "Model failed to extract intent" in command.update["error_logs"][0]["error"]
        )


@pytest.mark.asyncio
async def test_searching_node_error_degraded_path():
    state = {
        "intent_extraction": {
            "extracted_intent": {"company_name": "Apple", "ticker": "AAPL"}
        }
    }

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.intent_orchestrator.search_candidates",
        side_effect=Exception("Search Error"),
    ):
        command = await searching_node(state)

        assert command.goto == "clarifying"
        assert command.update["node_statuses"]["intent_extraction"] == "degraded"
        assert "Search tool failed" in command.update["error_logs"][0]["error"]


@pytest.mark.asyncio
async def test_decision_node_error_degraded_path():
    state = {
        "intent_extraction": {
            "ticker_candidates": [{"symbol": "AAPL", "confidence": 1.0}]
        }
    }

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.intent_orchestrator.parse_candidates",
        side_effect=Exception("Validation Error"),
    ):
        command = await decision_node(state)

        assert command.goto == "clarifying"
        assert command.update["node_statuses"]["intent_extraction"] == "degraded"
        assert "Decision logic crashed" in command.update["error_logs"][0]["error"]


@pytest.mark.asyncio
async def test_searching_node_serializes_domain_candidates_to_json():
    state = {
        "user_query": "Valuate GME",
        "intent_extraction": {
            "extracted_intent": {"company_name": "GameStop", "ticker": "GME"}
        },
    }

    candidates = [
        TickerCandidate(symbol="GME", name="GameStop Corp.", confidence=0.98),
        TickerCandidate(symbol="GMED", name="Globus Medical, Inc.", confidence=0.73),
    ]

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.intent_orchestrator.search_candidates",
        return_value=_SearchCandidatesOutcome(
            candidates=candidates,
            is_degraded=False,
        ),
    ):
        command = await searching_node(state)

    assert command.goto == "deciding"
    serialized = command.update["intent_extraction"]["ticker_candidates"]
    assert isinstance(serialized, list)
    assert serialized[0]["symbol"] == "GME"
    assert serialized[0]["name"] == "GameStop Corp."
    assert serialized[1]["symbol"] == "GMED"


@pytest.mark.asyncio
async def test_searching_node_marks_degraded_when_web_channel_degraded(caplog):
    state = {
        "user_query": "Valuate NVDA",
        "intent_extraction": {
            "extracted_intent": {"company_name": "NVIDIA", "ticker": "NVDA"}
        },
    }
    outcome = _SearchCandidatesOutcome(
        candidates=[
            TickerCandidate(symbol="NVDA", name="NVIDIA Corp.", confidence=0.98)
        ],
        is_degraded=True,
        degrade_error_code="INTENT_WEB_SEARCH_EMPTY",
        degrade_reason="no results found",
        fallback_mode="yahoo_only",
        degrade_source="web_search",
    )

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.intent_orchestrator.search_candidates",
        return_value=outcome,
    ):
        with caplog.at_level(logging.INFO):
            command = await searching_node(state)

    assert command.goto == "deciding"
    completed = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "intent_search_completed"
    ]
    assert completed
    assert completed[-1].fields.get("is_degraded") is True

    degraded_reason_logs = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "intent_search_degraded"
    ]
    assert degraded_reason_logs
    assert degraded_reason_logs[-1].error_code == "INTENT_WEB_SEARCH_EMPTY"


@pytest.mark.asyncio
async def test_extraction_completed_uses_null_resolved_ticker_for_empty_value(caplog):
    state = {"user_query": "Analyze NVIDIA"}

    class _IntentStub:
        company_name = "NVIDIA"
        ticker = ""
        is_valuation_request = True
        reasoning = "stub"

        def model_dump(self, *, mode: str = "python") -> dict[str, object]:
            return {
                "company_name": self.company_name,
                "ticker": self.ticker,
                "is_valuation_request": self.is_valuation_request,
                "reasoning": self.reasoning,
            }

    with patch(
        "src.workflow.nodes.intent_extraction.nodes.intent_orchestrator.extract_intent",
        return_value=_IntentStub(),
    ):
        with caplog.at_level(logging.INFO):
            command = await extraction_node(state)

    assert command.goto == "searching"
    completed = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "intent_extraction_completed"
    ]
    assert completed
    assert completed[-1].fields.get("resolved_ticker") is None
