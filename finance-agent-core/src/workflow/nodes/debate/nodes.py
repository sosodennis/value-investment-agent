import json
import os
from typing import Any

from langchain_core.messages import AIMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ...state import AgentState
from .prompts import (
    BEAR_AGENT_SYSTEM_PROMPT,
    BULL_AGENT_SYSTEM_PROMPT,
    MODERATOR_SYSTEM_PROMPT,
    VERDICT_PROMPT,
)
from .schemas import DebateConclusion

# --- LLM Shared Config ---
DEFAULT_MODEL = "mistralai/devstral-2512:free"


def get_llm(model: str = DEFAULT_MODEL, temperature: float = 0):
    """Factory for ChatOpenAI instance with OpenRouter support."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    base_url = "https://openrouter.ai/api/v1"

    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY")
        base_url = "https://api.openai.com/v1"

    return ChatOpenAI(
        model=model,
        temperature=temperature,
        openai_api_key=api_key,
        base_url=base_url,
    )


def debate_aggregator_node(state: AgentState) -> dict[str, Any]:
    """
    [Phase 1] Aggregator Node
    Consolidates data from News Research and Fundamental Analysis into
    a single 'analyst_reports' dictionary for the debate agents to consume.
    """
    print("--- Debate: Aggregating ground truth data ---")

    # Consolidate news and financials
    reports = {
        "news": state.financial_news_output,
        "financials": state.financial_reports,
        "ticker": state.resolved_ticker or state.ticker,
    }

    return {
        "analyst_reports": reports,
        "current_node": "debate_aggregator",
        "node_statuses": {"debate_aggregator": "done", "bull": "running"},
    }


async def bull_node(state: AgentState) -> dict[str, Any]:
    """
    [Phase 2] Bull Agent (The Growth Hunter)
    Role: Focus on catalysts, growth potential, and bullish news.
    """
    round_num = state.debate_current_round + 1
    ticker = state.resolved_ticker or state.ticker
    print(f"--- Debate: Bull Agent Node (Round {round_num}) ---")

    llm = get_llm()
    system_content = BULL_AGENT_SYSTEM_PROMPT.format(
        ticker=ticker, reports=json.dumps(state.analyst_reports, indent=2, default=str)
    )

    messages = [SystemMessage(content=system_content)] + state.debate_history

    response = await llm.ainvoke(messages)

    return {
        "debate_history": [AIMessage(content=response.content, name="GrowthHunter")],
        "bull_thesis": response.content,
        "current_node": "bull",
        "node_statuses": {"bull": "done", "bear": "running"},
    }


async def bear_node(state: AgentState) -> dict[str, Any]:
    """
    [Phase 2] Bear Agent (The Forensic Accountant)
    Role: Focus on risks, red flags, and challenging the Bull's narrative.
    """
    round_num = state.debate_current_round + 1
    ticker = state.resolved_ticker or state.ticker
    print(f"--- Debate: Bear Agent Node (Round {round_num}) ---")

    llm = get_llm()
    system_content = BEAR_AGENT_SYSTEM_PROMPT.format(
        ticker=ticker, reports=json.dumps(state.analyst_reports, indent=2, default=str)
    )

    # Note: State messages includes the Bull's just-finished reply
    messages = [SystemMessage(content=system_content)] + state.debate_history

    response = await llm.ainvoke(messages)

    return {
        "debate_history": [
            AIMessage(content=response.content, name="ForensicAccountant")
        ],
        "bear_thesis": response.content,
        "current_node": "bear",
        "node_statuses": {"bear": "done", "moderator": "running"},
    }


async def moderator_node(state: AgentState) -> dict[str, Any]:
    """
    [Phase 2/3] Moderator Agent (The Judge)
    Role: Decides if consensus is reached or if debate should continue/conclude.
    Also handles the final 'Verdict' synthesis in Phase 3.
    """
    round_num = state.debate_current_round + 1
    ticker = state.resolved_ticker or state.ticker
    print(f"--- Debate: Moderator Node (Round {round_num}) ---")

    llm = get_llm()

    if round_num < 3:
        # Standard Critique/Redirect Round
        system_content = MODERATOR_SYSTEM_PROMPT.format(
            ticker=ticker,
            reports=json.dumps(state.analyst_reports, indent=2, default=str),
        )
        messages = [SystemMessage(content=system_content)] + state.debate_history
        response = await llm.ainvoke(messages)

        return {
            "debate_history": [AIMessage(content=response.content, name="Judge")],
            "debate_current_round": round_num,
            "current_node": "moderator",
            "node_statuses": {"moderator": "done"},
        }
    else:
        # Final Round: Synthesis of the DebateConclusion
        print("--- Debate: Final Synthesis (Verdict) ---")
        history_text = "\n\n".join(
            [f"{msg.name or 'Agent'}: {msg.content}" for msg in state.debate_history]
        )
        verdict_system = VERDICT_PROMPT.format(ticker=ticker, history=history_text)

        # Attempt structured output - fallback to manual parse if model fails
        try:
            structured_llm = llm.with_structured_output(DebateConclusion)
            conclusion = await structured_llm.ainvoke(verdict_system)
            conclusion_data = conclusion.model_dump()
        except Exception as e:
            print(f"!!! Debate: Structured output failed: {e}. Falling back to text.")
            # Simple fallback (could be or refined more)
            conclusion_data = {
                "winning_thesis": "See history",
                "primary_catalyst": "Unknown",
                "primary_risk": "Unextracted",
                "direction": "NEUTRAL",
                "confidence_score": 0.5,
                "debate_rounds": round_num,
                "supporting_factors": [],
            }

        conclusion_data["debate_rounds"] = round_num

        return {
            "debate_conclusion": conclusion_data,
            "debate_current_round": round_num,
            "current_node": "moderator",
            "node_statuses": {"moderator": "done", "executor": "running"},
        }
