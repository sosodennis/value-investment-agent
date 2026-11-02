from langchain_core.messages import AIMessage, HumanMessage

from src.agents.debate.application.state_readers import (
    bear_thesis_from_state,
    bull_thesis_from_state,
    debate_context_from_state,
    get_last_message_from_role,
    history_from_state,
    resolved_ticker_from_state,
)
from src.shared.cross_agent.domain.market_identity import CompanyProfile


def test_resolved_ticker_from_state():
    state = {"company_profile": CompanyProfile(ticker="  AAPL  ", name="Apple")}
    assert resolved_ticker_from_state(state) == "AAPL"


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


def test_thesis_from_state_reads_top_level_and_normalizes() -> None:
    state = {"bull_thesis": "  bull text  ", "bear_thesis": "bear text"}
    assert bull_thesis_from_state(state) == "bull text"
    assert bear_thesis_from_state(state) == "bear text"


def test_thesis_from_state_returns_none_for_empty_or_missing() -> None:
    assert bull_thesis_from_state({"bull_thesis": "   "}) is None
    assert bear_thesis_from_state({}) is None
