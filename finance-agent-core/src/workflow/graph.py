from typing import Any, Dict, Optional, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .state import AgentState
from .nodes import executor_node, auditor_node, calculation_node
from .nodes.planner.graph import planner_subgraph
from .nodes.planner.structures import ValuationModel
from .nodes.planner.tools import get_company_profile
from .nodes.planner.logic import select_valuation_model


# --- Routers ---
def planner_router(state: AgentState) -> Literal["executor", "planner_human_review"]:
    # Check if planner needs clarification
    if state.get("status") == "waiting_for_human":
        return "planner_human_review"
    planner_out = state.get("planner_output", {})
    if planner_out.get("status") == "clarification_needed":
        return "planner_human_review"
    if not state.get("ticker") or not state.get("model_type"):
        return "planner_human_review"
    return "executor"

def audit_condition(state: AgentState) -> Literal["human_review", "executor"]:
    if state["audit_report"]["passed"]:
        return "human_review"
    else:
        print(f"Audit Failed: {state['audit_report']['messages']}")
        return "human_review" 

# --- Build Graph ---
builder = StateGraph(AgentState)

builder.add_node("planner", planner_subgraph)
builder.add_node("executor", executor_node)
builder.add_node("auditor", auditor_node)

def resolve_human_review(state: AgentState) -> Dict[str, Any]:
    """
    Called after human review interrupt.
    If user provided input, use it.
    If user just resumed without input, pick the top candidate to break potential loops.
    """
    # 1. Check if user already resolved it manually (provided the ticker directly)
    if state.get("ticker") and state.get("model_type"):
        return {} # State is good

    # 2. Check if user provided a specific symbol selection (e.g. from UI dropdown)
    # We allow 'selected_symbol' or 'ticker' to be set during interrupt
    selected_symbol = state.get("selected_symbol") or state.get("ticker")
    print(f"DEBUG resolve_human_review: selected_symbol={selected_symbol}, ticker={state.get('ticker')}, model_type={state.get('model_type')}")
    
    if selected_symbol and not state.get("model_type"):
        # User picked a symbol, but we need to run logic to get profile/model
        print(f"User selected symbol: {selected_symbol}. Resolving details...")
        
        profile = get_company_profile(selected_symbol)
        if not profile:
            # If invalid symbol, we might want to return empty to loop back to planner?
            # Or set an error status?
            print(f"Could not find profile for {selected_symbol}")
            return {} 
            
        model, reasoning = select_valuation_model(profile)
        
        # Map model
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
            "ticker": selected_symbol,
            "model_type": model_type,
            "resolved_ticker": selected_symbol,
            "company_profile": profile.model_dump(),
            "planner_output": {
                "ticker": selected_symbol,
                "model_type": model.value,
                "reasoning": "User selected candidate. " + reasoning
            }
        }

    # 3. If no input provided, we default to the top candidate to avoid infinite loops.
    # The user had a chance to interrupt and provide 'selected_symbol'. 
    # If they just resumed, we assume they accept the default/best option.
    print("No user selection found. Defaulting to top candidate to proceed.")
    
    candidates = state.get("ticker_candidates")
    if candidates:
        top_cand = candidates[0]
        ticker = top_cand.get("symbol") if isinstance(top_cand, dict) else top_cand.symbol
        
        # Re-run logic
        profile = get_company_profile(ticker)
        if not profile:
            return {} 
            
        model, reasoning = select_valuation_model(profile)
        
        # Map model
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
            "ticker": ticker,
            "model_type": model_type,
            "resolved_ticker": ticker,
            "company_profile": profile.model_dump(),
            "planner_output": {
                "ticker": ticker,
                "model_type": model.value,
                "reasoning": "Auto-resolved (default fallback) after human review. " + reasoning
            }
        }

    return {}

builder.add_node("planner_human_review", resolve_human_review) 
builder.add_node("calculator", calculation_node)

builder.add_edge(START, "planner")

builder.add_conditional_edges("planner", planner_router, {
    "executor": "executor",
    "planner_human_review": "planner_human_review"
})

def human_review_router(state: AgentState) -> Literal["executor", "planner"]:
    # If we have the necessary info, proceed to executor
    print(f"DEBUG human_review_router: ticker={state.get('ticker')}, model_type={state.get('model_type')}")
    if state.get("ticker") and state.get("model_type"):
        return "executor"
    # Otherwise, go back to planner node to re-evaluate or ask again
    return "planner"

builder.add_conditional_edges("planner_human_review", human_review_router, {
    "executor": "executor",
    "planner": "planner"
})

builder.add_edge("executor", "auditor")

builder.add_conditional_edges("auditor", audit_condition, {
    "human_review": "calculator", 
    "executor": "executor" 
})

builder.add_edge("calculator", END)

# Compile with checkpointer for HITL
memory = MemorySaver()
graph = builder.compile(checkpointer=memory, interrupt_before=["calculator", "planner_human_review"])

