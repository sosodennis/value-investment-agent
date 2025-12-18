from typing import Any, Dict, Optional, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .state import AgentState
from .nodes import executor_node, auditor_node, calculation_node
from .nodes.planner.graph import planner_subgraph


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
# Human review for planner (placeholder node for interruption)
builder.add_node("planner_human_review", lambda x: x) 
builder.add_node("calculator", calculation_node)

builder.add_edge(START, "planner")

builder.add_conditional_edges("planner", planner_router, {
    "executor": "executor",
    "planner_human_review": "planner_human_review"
})

builder.add_edge("planner_human_review", END) # Stop and wait for user to fix input

builder.add_edge("executor", "auditor")

builder.add_conditional_edges("auditor", audit_condition, {
    "human_review": "calculator", 
    "executor": "executor" 
})

builder.add_edge("calculator", END)

# Compile with checkpointer for HITL
memory = MemorySaver()
graph = builder.compile(checkpointer=memory, interrupt_before=["calculator", "planner_human_review"])

