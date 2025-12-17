from typing import Any, Dict, Optional, TypedDict, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from .nodes import planner_node, executor_node, auditor_node, calculation_node

# Define State
class AgentState(TypedDict):
    ticker: str
    model_type: str # 'saas' or 'bank'
    params: Optional[Dict[str, Any]] # Serialized JSON of params
    audit_report: Optional[Dict[str, Any]] # {passed: bool, messages: []}
    valuation_result: Optional[Dict[str, Any]]

# --- Router ---
def audit_condition(state: AgentState) -> Literal["human_review", "executor"]:
    if state["audit_report"]["passed"]:
        return "human_review"
    else:
        print(f"Audit Failed: {state['audit_report']['messages']}")
        # In a real agent, we loop back to executor with feedback.
        # For this prototype, we just stop or go to human anyway so they see error.
        # Let's go to human_review but Human sees error.
        return "human_review" 

# --- Build Graph ---
builder = StateGraph(AgentState)

builder.add_node("planner", planner_node)
builder.add_node("executor", executor_node)
builder.add_node("auditor", auditor_node)
# Human review is implicit via interrupt_before
builder.add_node("calculator", calculation_node)

builder.add_edge(START, "planner")
builder.add_edge("planner", "executor")
builder.add_edge("executor", "auditor")

builder.add_conditional_edges("auditor", audit_condition, {
    "human_review": "calculator", # Actually we interrupt before calculator
    "executor": "executor" # Loop back if needed (disabled for now)
})

builder.add_edge("calculator", END)

# Compile with checkpointer for HITL
memory = MemorySaver()
graph = builder.compile(checkpointer=memory, interrupt_before=["calculator"])

