from src.shared.kernel.tools.incident_logging import (
    build_replay_diagnostics,
    log_boundary_event,
)
from src.shared.kernel.tools.logger import get_logger


def test_build_replay_diagnostics_collects_artifact_refs() -> None:
    state = {
        "ticker": "AAPL",
        "current_node": "aggregator_node",
        "messages": [{"content": "hello"}],
        "node_statuses": {"financial_news_research": "running"},
        "internal_progress": {"aggregator_node": "running"},
        "financial_news_research": {
            "search_artifact_id": "search-1",
            "selection_artifact_id": "selection-1",
            "report_id": "report-1",
        },
    }

    replay = build_replay_diagnostics(state, node="news.aggregator")

    assert replay["node"] == "news.aggregator"
    assert replay["ticker"] == "AAPL"
    assert replay["message_count"] == 1
    artifact_refs = replay["artifact_refs"]
    assert isinstance(artifact_refs, dict)
    assert artifact_refs["financial_news_research.search_artifact_id"] == "search-1"
    assert (
        artifact_refs["financial_news_research.selection_artifact_id"] == "selection-1"
    )
    assert artifact_refs["financial_news_research.report_id"] == "report-1"


def test_log_boundary_event_returns_schema_fields() -> None:
    logger = get_logger(__name__)
    record = log_boundary_event(
        logger,
        node="intent.searching",
        artifact_id=None,
        contract_kind="workflow_state",
        error_code="OK",
        state={"ticker": "AAPL"},
    )

    assert record["node"] == "intent.searching"
    assert record["artifact_id"] is None
    assert record["contract_kind"] == "workflow_state"
    assert record["error_code"] == "OK"
    assert "replay" in record
