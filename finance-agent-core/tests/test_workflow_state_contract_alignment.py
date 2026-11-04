from src.workflow.state import AgentState


def test_root_state_contains_only_shared_transport_and_workflow_fields() -> None:
    assert set(AgentState.__annotations__) == {
        "user_query",
        "messages",
        "company_profile",
        "artifact_references",
        "workflow_activity_statuses",
        "active_activity_id",
        "workflow_activity_updates",
        "error_logs",
        "valuation_request",
    }
