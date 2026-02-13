from langchain_core.messages import AIMessage, HumanMessage

from src.agents.debate.application.state_readers import (
    artifact_ref_id_from_context,
    debate_context_from_state,
    get_last_message_from_role,
    history_from_state,
    resolved_ticker_from_state,
)


def test_resolved_ticker_from_state():
    state = {"intent_extraction": {"resolved_ticker": "  AAPL  "}}
    assert resolved_ticker_from_state(state) == "AAPL"


def test_artifact_ref_id_from_context():
    ctx = {"artifact": {"reference": {"artifact_id": "art-123"}}}
    assert artifact_ref_id_from_context(ctx) == "art-123"


def test_history_and_last_message_reader():
    history = [
        HumanMessage(content="hi"),
        AIMessage(content="bull text", name="GrowthHunter"),
        AIMessage(
            content="bear text",
            additional_kwargs={"name": "ForensicAccountant"},
        ),
    ]
    state = {"history": history}

    parsed_history = history_from_state(state)
    assert len(parsed_history) == 3
    assert get_last_message_from_role(parsed_history, "GrowthHunter") == "bull text"
    assert (
        get_last_message_from_role(parsed_history, "ForensicAccountant") == "bear text"
    )


def test_debate_context_from_state():
    state = {"debate": {"bull_thesis": "x", "bear_thesis": "y"}}
    ctx = debate_context_from_state(state)
    assert ctx.get("bull_thesis") == "x"
