"""
Planner Sub-graph implementation.
Handles the flow: Extract Intent -> Search/Verify -> Clarify (if needed).
"""

from typing import Annotated, Dict, Any, List, Literal
from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage

from .extraction import extract_intent
from .tools import search_ticker, web_search, get_company_profile
from .logic import select_valuation_model, should_request_clarification
from .structures import PlannerOutput, ValuationModel
from ...state import AgentState


# --- Nodes ---

def extraction_node(state: AgentState) -> Dict[str, Any]:
    """Extract company and model from user query."""
    intent = extract_intent(state["user_query"])
    return {
        "extracted_intent": intent.model_dump(),
        "status": "searching"
    }

def searching_node(state: AgentState) -> Dict[str, Any]:
    """Search for the ticker based on extracted intent."""
    intent = state["extracted_intent"]
    query = intent.get("ticker") or intent.get("company_name")
    
    if not query:
        return {"status": "clarifying"}

    # 1. Try Yahoo Finance Search
    candidates = search_ticker(query)
    
    # 2. If no candidates, try web search
    if not candidates:
        search_results = web_search(f"What is the stock ticker for {query}?")
        print(search_results)
        # Re-try search with web results? Or just let LLM decide?
        # For simplicity, we'll try to refine the query and search again once
        refined_candidates = search_ticker(query) # Placeholder for more complex logic
        candidates = refined_candidates

    return {
        "ticker_candidates": [c.model_dump() for c in candidates],
        "status": "deciding"
    }

def decision_node(state: AgentState) -> Dict[str, Any]:
    """Decide if ticker is resolved or needs clarification."""
    candidates = state["ticker_candidates"]
    
    if not candidates:
        return {"status": "clarifying"}

    # Check for ambiguity
    # Conversion back to objects for logic function
    from .structures import TickerCandidate
    candidate_objs = [TickerCandidate(**c) for c in candidates]
    
    if should_request_clarification(candidate_objs):
        return {"status": "clarifying"}
    
    # Resolved
    resolved_ticker = candidate_objs[0].symbol
    profile = get_company_profile(resolved_ticker)
    
    if not profile:
        return {"status": "clarifying"}

    # Select model
    model, reasoning = select_valuation_model(profile)
    
    # Override with user preference if valid
    user_pref = state["extracted_intent"].get("model_preference")
    if user_pref:
        model = ValuationModel(user_pref)
        reasoning = f"User explicitly requested {model.value}. " + reasoning

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

    return {
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
    }

def clarification_node(state: AgentState) -> Dict[str, Any]:
    """Notify that clarification is needed. In LangGraph main loop, this triggers an interrupt."""
    # This node doesn't do much on its own, it's a marker for the main graph to stop.
    # In a real sub-agent, we might format a message for the user.
    return {
        "status": "waiting_for_human",
        "planner_output": {
            "status": "clarification_needed",
            "candidates": state.get("ticker_candidates"),
            "intent": state.get("extracted_intent")
        }
    }


# --- Router ---

def router(state: AgentState) -> Literal["searching", "deciding", "clarifying", "done", "extraction"]:
    status = state.get("status")
    if status == "searching":
        return "searching"
    if status == "deciding":
        return "deciding"
    if status == "clarifying":
        return "clarifying"
    if status == "done":
        return END
    return "extraction"

# --- Build Sub-graph ---
def create_planner_subgraph():
    builder = StateGraph(AgentState)
    
    builder.add_node("extraction", extraction_node)
    builder.add_node("searching", searching_node)
    builder.add_node("deciding", decision_node)
    builder.add_node("clarifying", clarification_node)
    
    builder.add_edge(START, "extraction")
    builder.add_conditional_edges("extraction", lambda x: "searching")
    builder.add_conditional_edges("searching", lambda x: "deciding")
    builder.add_conditional_edges("deciding", lambda x: x["status"], {
        "done": END,
        "clarifying": "clarifying"
    })
    builder.add_edge("clarifying", END) # End and let main graph handle interrupt
    
    return builder.compile()

planner_subgraph = create_planner_subgraph()
