import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from src.interface.adapters import adapt_langgraph_event
from src.interface.schemas import AgentOutputArtifact


def test_ta_event_adaptation():
    print("\n--- Testing Technical Analysis Event Adaptation ---")

    # Simulate the raw output from process_technical node (on_chain_end)
    # This matches what `process_technical_node` returns (dict)

    # Construct a Mock Artifact
    mock_artifact = AgentOutputArtifact(
        summary="TA Completed",
        preview={"signal": "BUY", "z_score": 2.5},
        reference={
            "artifact_id": "test-id",
            "type": "ta_data",
            "download_url": "http://localhost/test",
        },
    )

    # The update dict (what is inside Command)
    state_update = {
        "technical_analysis": {"some_internal_field": 123, "artifact": mock_artifact},
        "node_statuses": {"technical_analysis": "done"},
    }

    # Simulate Command Object (LangGraph v0.2+)
    # Since we can't easily reproduce the exact runtime object if it's Pydantic-based without environment,
    # we will test both the 'object with .update' and 'dict with update key' cases.

    # Case 1: Dict with 'update' and 'goto' (Serialized Command)
    raw_output_dict = {"update": state_update, "goto": "__end__"}

    # Construct the LangGraph event
    event = {
        "event": "on_chain_end",
        "name": "process_technical",
        "data": {
            "output": raw_output_dict  # Passing the "Command-like" dict
        },
        "metadata": {
            "agent_id": "technical_analysis",
            "langgraph_node": "process_technical",
        },
        "tags": ["hide_stream"],
    }

    # Run the adapter
    print(f"Input Event Metadata: {event['metadata']}")
    print(f"Input Output (Simulating Command): {list(raw_output_dict.keys())}")

    events = adapt_langgraph_event(event, "thread_1", 1, "run_1")

    print(f"\nGenerated {len(events)} events:")
    for e in events:
        print(f"  - Type: {e.type}, Source: {e.source}")
        if e.type == "state.update":
            print(f"    Data Keys: {list(e.data.keys())}")
            print(f"    Preview: {e.data.get('preview')}")

    # Verification
    state_updates = [
        e
        for e in events
        if e.type == "state.update" and e.source == "technical_analysis"
    ]
    if state_updates:
        print("\n✅ SUCCESS: Found state.update event for technical_analysis")
    else:
        print("\n❌ FAILURE: No state.update event generated")


if __name__ == "__main__":
    test_ta_event_adaptation()
