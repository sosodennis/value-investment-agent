from typing import Any, Dict, Optional, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command
from langchain_core.callbacks.manager import adispatch_custom_event

from .state import AgentState
from .nodes import executor_node, auditor_node, calculation_node
from .nodes.planner.graph import planner_subgraph
from .nodes.planner.structures import ValuationModel
from .nodes.planner.tools import get_company_profile
from .nodes.planner.logic import select_valuation_model


def approval_node(state: AgentState) -> Command:
    """
    Waits for human approval using the interrupt() function.
    """
    print("--- Approval: Requesting human approval ---")
    
    # Access Pydantic fields
    if state.approved:
        return Command(goto="calculator")
        
    audit_passed = False
    audit_messages = []
    if state.audit_output:
        audit_passed = state.audit_output.passed
        audit_messages = state.audit_output.messages

    # Trigger interrupt. This pauses the graph and returns the user input when resumed.
    ans = interrupt({
        "type": "approval_request",
        "action": "calculate_valuation",
        "details": {
            "ticker": state.ticker,
            "model": state.model_type,
            "audit_passed": audit_passed,
            "audit_messages": audit_messages
        }
    })

    # When resumed, ans will contain the payload sent from frontend (e.g. { "approved": true })
    if ans.get("approved"):
        print("✅ Received human approval.")
        return Command(update={"approved": True}, goto="calculator")
    else:
        print("❌ Final approval rejected.")
        return Command(update={"approved": False}, goto=END)


# --- Build Graph ---
builder = StateGraph(AgentState)

builder.add_node("planner", planner_subgraph)
builder.add_node("executor", executor_node)
builder.add_node("auditor", auditor_node)
builder.add_node("approval", approval_node)
builder.add_node("calculator", calculation_node)

builder.add_edge(START, "planner")
# Note: planner_subgraph handles its own END, but we need an edge from planner (the node) to executor
builder.add_edge("planner", "executor")
# Nodes below return Command(goto=...) so explicit edges are removed where possible.
# Note: Actually, LangGraph node-to-node edges can be fully replaced by Command.
# If planner is a subgraph, its completion triggers the next edge in the parent graph.
builder.add_edge("calculator", END)

# Compile with checkpointer.
# We don't need interrupt_before because we call interrupt() inside nodes.
memory = MemorySaver()
graph = builder.compile(checkpointer=memory)

