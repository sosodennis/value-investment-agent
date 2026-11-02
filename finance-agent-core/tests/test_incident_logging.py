from src.shared.kernel.tools.incident_logging import (
    build_replay_diagnostics,
    log_boundary_event,
)
from src.shared.kernel.tools.logger import get_logger


def test_build_replay_diagnostics_collects_artifact_refs() -> None:
    state = {
        "company_profile": {"ticker": "AAPL", "name": "Apple Inc."},
        "active_activity_id": "aggregator_node",
        "messages": [{"content": "hello"}],
        "workflow_activity_statuses": {"financial_news_research": "running"},
        "workflow_activity_updates": {"aggregator_node": "running"},
        "artifact_references": {
            "financial_reports": {
                "artifact_id": "financial-reports-1",
                "download_url": "/api/v1/artifacts/financial-reports-1",
                "type": "financial_reports",
            },
            "news_analysis": {
                "artifact_id": "report-1",
                "download_url": "/api/v1/artifacts/report-1",
                "type": "news_analysis_report",
            },
        },
    }

    replay = build_replay_diagnostics(state, node="news.aggregator")

    assert replay["node"] == "news.aggregator"
    assert replay["ticker"] == "AAPL"
    assert replay["message_count"] == 1
    artifact_refs = replay["artifact_refs"]
    assert isinstance(artifact_refs, dict)
    assert (
        artifact_refs["artifact_references.financial_reports.artifact_id"]
        == "financial-reports-1"
    )
    assert artifact_refs["artifact_references.news_analysis.artifact_id"] == "report-1"


def test_log_boundary_event_returns_schema_fields() -> None:
    logger = get_logger(__name__)
    record = log_boundary_event(
        logger,
        node="intent.searching",
        artifact_id=None,
        contract_kind="workflow_state",
        error_code="OK",
        state={"company_profile": {"ticker": "AAPL", "name": "Apple Inc."}},
    )

    assert record["node"] == "intent.searching"
    assert record["artifact_id"] is None
    assert record["contract_kind"] == "workflow_state"
    assert record["error_code"] == "OK"
    assert "replay" in record
