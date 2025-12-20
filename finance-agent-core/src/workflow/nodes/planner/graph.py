"""
Planner Sub-graph implementation.
Handles the flow: Extract Intent -> Search/Verify -> Clarify (if needed).
Uses Command and interrupt for control flow.
"""

from typing import Annotated, Dict, Any, List, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage

from .extraction import extract_intent, extract_candidates_from_search, deduplicate_candidates
from .tools import search_ticker, web_search, get_company_profile
from .logic import select_valuation_model, should_request_clarification
from .structures import PlannerOutput, ValuationModel
from ...state import AgentState


# --- Nodes ---

def extraction_node(state: AgentState) -> Command:
    """Extract company and model from user query."""
    user_query = state.get("user_query")
    if not user_query:
        print("--- Planner: No query provided, requesting clarification ---")
        return Command(
            update={
                "status": "clarifying",
                "planner_output": {"status": "clarification_needed", "error": "No query provided"}
            },
            goto="clarifying"
        )
    
    print(f"--- Planner: Extracting intent from: {user_query} ---")
    intent = extract_intent(user_query)
    return Command(
        update={
            "extracted_intent": intent.model_dump(),
            "status": "searching"
        },
        goto="searching"
    )

def searching_node(state: AgentState) -> Command:
    """Search for the ticker based on extracted intent."""
    intent = state.get("extracted_intent", {})
    query = intent.get("ticker") or intent.get("company_name")
    
    if not query:
        print("--- Planner: Search query missing, requesting clarification ---")
        return Command(
            update={"status": "clarifying"},
            goto="clarifying"
        )

    print(f"--- Planner: Searching for: {query} ---")
    candidate_map = {}

    # 1. Try Yahoo Finance Search
    yf_candidates = search_ticker(query)
    for c in yf_candidates:
        candidate_map[c.symbol] = c

    # 2. Web Search fallback
    print(f"Running web search fallback for: {query}")
    search_results = web_search(f"stock ticker symbol for {query} and company name")
    
    web_candidates = extract_candidates_from_search(query, search_results)
    
    for c in web_candidates:
        if c.symbol in candidate_map:
             if c.confidence > candidate_map[c.symbol].confidence:
                 candidate_map[c.symbol] = c
        else:
            candidate_map[c.symbol] = c

    final_candidates = deduplicate_candidates(list(candidate_map.values()))
    print(f"Final candidates: {[c.symbol for c in final_candidates]}")

    return Command(
        update={
            "ticker_candidates": [c.model_dump() for c in final_candidates],
            "status": "deciding"
        },
        goto="deciding"
    )

def decision_node(state: AgentState) -> Command:
    """Decide if ticker is resolved or needs clarification."""
    candidates = state.get("ticker_candidates", [])
    
    if not candidates:
        print("--- Planner: No candidates found, requesting clarification ---")
        return Command(
            update={"status": "clarifying"},
            goto="clarifying"
        )

    # Check for ambiguity
    from .structures import TickerCandidate
    candidate_objs = [TickerCandidate(**c) for c in candidates]
    
    if should_request_clarification(candidate_objs):
        print("--- Planner: Ambiguity detected, requesting clarification ---")
        return Command(
            update={"status": "clarifying"},
            goto="clarifying"
        )
    
    # Resolved
    resolved_ticker = candidate_objs[0].symbol
    print(f"--- Planner: Ticker resolved to {resolved_ticker} ---")
    profile = get_company_profile(resolved_ticker)
    
    if not profile:
        print(f"--- Planner: Could not fetch profile for {resolved_ticker}, requesting clarification ---")
        return Command(
            update={"status": "clarifying"},
            goto="clarifying"
        )

    # Select model
    model, reasoning = select_valuation_model(profile)
    
    # Override with user preference
    user_pref = state.get("extracted_intent", {}).get("model_preference")
    if user_pref:
        try:
            model = ValuationModel(user_pref)
            reasoning = f"User explicitly requested {model.value}. " + reasoning
        except ValueError:
            pass

    # Map model_type for calculation node compatibility
    model_type_map = {
        ValuationModel.DCF_GROWTH: "saas",
        ValuationModel.DCF_STANDARD: "saas",
        ValuationModel.DDM: "bank",
        ValuationModel.FFO: "saas",
        ValuationModel.EV_REVENUE: "saas",
        ValuationModel.EV_EBITDA: "saas",
    }
    model_type = model_type_map.get(model, "saas")

    return Command(
        update={
            "ticker": resolved_ticker,
            "model_type": model_type,
            "resolved_ticker": resolved_ticker,
            "company_profile": profile.model_dump(),
            "planner_output": {
                "ticker": resolved_ticker,
                "model_type": model.value,
                "company_name": profile.name,
                "sector": profile.sector,
                "industry": profile.industry,
                "reasoning": reasoning
            },
            "status": "done"
        },
        goto=END
    )

def clarification_node(state: AgentState) -> Command:
    """
    Triggers an interrupt to ask the user to select a ticker or provide clarification.
    """
    print("--- Planner: Ticker Ambiguity Detected. Waiting for user input... ---")
    
    # Trigger interrupt with candidates
    user_input = interrupt({
        "type": "ticker_selection",
        "candidates": state.get("ticker_candidates"),
        "intent": state.get("extracted_intent"),
        "reason": "Multiple tickers found or ambiguity detected."
    })

    # user_input is what the frontend sends back, e.g. { "selected_symbol": "GOOGL" }
    selected_symbol = user_input.get("selected_symbol") or user_input.get("ticker")
    
    if not selected_symbol:
        # Fallback to top candidate if resumed without choice
        candidates = state.get("ticker_candidates", [])
        if candidates:
            top = candidates[0]
            selected_symbol = top.get("symbol") if isinstance(top, dict) else top.symbol

    if selected_symbol:
        print(f"✅ User selected or fallback symbol: {selected_symbol}. Resolving...")
        profile = get_company_profile(selected_symbol)
        if profile:
            model, reasoning = select_valuation_model(profile)
            model_type_map = {
                ValuationModel.DCF_GROWTH: "saas",
                ValuationModel.DCF_STANDARD: "saas",
                ValuationModel.DDM: "bank",
                ValuationModel.FFO: "saas",
                ValuationModel.EV_REVENUE: "saas",
                ValuationModel.EV_EBITDA: "saas",
            }
            model_type = model_type_map.get(model, "saas")

            return Command(
                update={
                    "ticker": selected_symbol,
                    "model_type": model_type,
                    "resolved_ticker": selected_symbol,
                    "company_profile": profile.model_dump(),
                    "planner_output": {
                        "ticker": selected_symbol,
                        "model_type": model.value,
                        "reasoning": "Resolved via human-in-the-loop. " + reasoning
                    },
                    "status": "done"
                },
                goto=END
            )

    # If even fallback fails, retry extraction
    print("--- Planner: Resolution failed, retrying extraction ---")
    return Command(
        update={"status": "extraction"},
        goto="extraction"
    )


from langgraph.checkpoint.memory import MemorySaver

# --- Build Sub-graph ---
def create_planner_subgraph():
    builder = StateGraph(AgentState)
    
    builder.add_node("extraction", extraction_node)
    builder.add_node("searching", searching_node)
    builder.add_node("deciding", decision_node)
    builder.add_node("clarifying", clarification_node)
    
    builder.add_edge(START, "extraction")
    # Transitions are handled by Command() in each node
    
    memory = MemorySaver()
    return builder.compile(checkpointer=memory)

planner_subgraph = create_planner_subgraph()
