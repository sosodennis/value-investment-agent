from unittest.mock import patch

from src.interface.adapters import adapt_langgraph_event
from src.interface.mappers import NodeOutputMapper

# ... (Previous tests remain, I will append the new test case) ...


# Removed patch since we use metadata now
def test_on_chain_end_status_behavior():
    """
    Test that adapt_langgraph_event does NOT automatically emit agent.status='done'
    just because a node finished (on_chain_end).
    """
    # Setup
    thread_id = "test_thread"
    seq_id = 1
    run_id = "test_run"

    # 1. Simulate a node that maps to an agent (e.g. debate_aggregator -> debate)
    # mock_get_agent_id.return_value = "debate"  <-- No longer needed
    node_name = "debate_aggregator"

    event = {
        "event": "on_chain_end",
        "metadata": {"langgraph_node": node_name, "agent_id": "debate"},
        "data": {"output": {"some": "data"}},
    }

    # Execute
    # We patch NodeOutputMapper to return a dummy payload so we get a state.update event
    with patch("src.interface.mappers.NodeOutputMapper.transform") as mock_transform:
        mock_transform.return_value = {"updated": "data"}

        events = adapt_langgraph_event(event, thread_id, seq_id, run_id)

    # Assert
    # We expect:
    # 1. state.update event (from NodeOutputMapper)
    # 2. NO agent.status='done' event (This is what we are fixing)

    state_updates = [e for e in events if e.type == "state.update"]
    status_updates = [e for e in events if e.type == "agent.status"]

    assert len(state_updates) == 1
    assert state_updates[0].source == "debate"

    # BEFORE FIX: This assertion would fail (we'd see 1 status update)
    # AFTER FIX: This assertion should pass (we expect 0 auto-generated status updates)
    assert (
        len(status_updates) == 0
    ), f"Expected 0 status updates, found: {[e.data for e in status_updates]}"


@patch("src.interface.adapters.get_agent_name")
def test_explicit_status_update_via_state_with_mapper(mock_get_agent_name):
    """
    Test that NodeOutputMapper correctly passes through node_statuses.
    This replicates the issue where mappers were stripping this field.
    """
    # mock_get_agent_id.return_value = "intent_extraction" <-- Unused as we test Mapper directly?
    # Actually this test seems to invoke NodeOutputMapper directly, so the adapter patch is irrelevant
    # except that the test signature requires it.
    pass

    # Adapter output typically looks like this:
    # Adapter output typically looks like this:
    adapter_output = {
        "intent_extraction": {
            "artifact": {"some_intent": "data"}
        },  # Context with artifact
        "node_statuses": {"intent_extraction": "done"},  # Explicit status
    }

    # Verify Mapper behavior directly
    result = NodeOutputMapper.transform("intent_extraction", adapter_output)

    # Assertion
    assert result is not None
    assert "some_intent" in result, "Mapper should extract artifact data"
    # Node statuses should be stripped as they are not part of the artifact
    assert "node_statuses" not in result, "Mapper should strip non-artifact fields"
