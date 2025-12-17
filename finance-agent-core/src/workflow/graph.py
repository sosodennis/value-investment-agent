from typing import Annotated, Any, Dict, Optional, TypedDict, Union, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
import json

from ..skills.valuation_saas.schemas import SaaSParams
from ..skills.valuation_bank.schemas import BankParams
from .manager import SkillRegistry

# Define State
class AgentState(TypedDict):
    ticker: str
    model_type: str # 'saas' or 'bank'
    params: Optional[Dict[str, Any]] # Serialized JSON of params
    audit_report: Optional[Dict[str, Any]] # {passed: bool, messages: []}
    valuation_result: Optional[Dict[str, Any]]

# --- Nodes ---

def planner_node(state: AgentState):
    # In a real implementation, LLM decides model_type based on ticker description.
    # Here we assume it's passed in or heuristic.
    print(f"--- Planner: Selected {state['model_type']} for {state['ticker']} ---")
    return {"model_type": state["model_type"]}

def executor_node(state: AgentState):
    # This node simulates extraction using LLM.
    # In Mock mode, we generate dummy data based on schema.
    print(f"--- Executor: Extracting parameters for {state['model_type']} ---")
    
    skill = SkillRegistry.get_skill(state["model_type"])
    if not skill:
        raise ValueError(f"Unknown model type: {state['model_type']}")
        
    schema = skill["schema"]
    
    # MOCK DATA GENERATION
    if state['model_type'] == 'saas':
        # Dummy data for SaaS
        mock_data = {
            "ticker": state["ticker"],
            "rationale": "Mocked extraction from 10-K",
            "initial_revenue": 100.0,
            "growth_rates": [0.20, 0.18, 0.15, 0.12, 0.10],
            "operating_margins": [0.10, 0.12, 0.15, 0.18, 0.20],
            "tax_rate": 0.21,
            "da_rates": [0.05]*5,
            "capex_rates": [0.05]*5,
            "wc_rates": [0.02]*5,
            "sbc_rates": [0.10, 0.09, 0.08, 0.07, 0.06],
            "wacc": 0.10,
            "terminal_growth": 0.03
        }
    elif state['model_type'] == 'bank':
        # Dummy data for Bank
        mock_data = {
             "ticker": state["ticker"],
             "rationale": "Mocked Bank Data",
             "initial_net_income": 500.0,
             "income_growth_rates": [0.05, 0.05, 0.04, 0.04, 0.03],
             "rwa_intensity": 0.02, # 2% RoRWA
             "tier1_target_ratio": 0.12,
             "initial_capital": 6000.0,
             "cost_of_equity": 0.08,
             "terminal_growth": 0.02
        }
    
    # Validate structure via Pydantic (ensure it matches)
    try:
        validated = schema(**mock_data)
        return {"params": validated.model_dump()}
    except Exception as e:
        print(f"Extraction Failed: {e}")
        return {}


def auditor_node(state: AgentState):
    print("--- Auditor: Checking parameters ---")
    params_dict = state["params"]
    model_type = state["model_type"]
    skill = SkillRegistry.get_skill(model_type)
    
    schema = skill["schema"]
    audit_func = skill["auditor"]
    
    # Rehydrate Pydantic object
    params_obj = schema(**params_dict)
    
    result = audit_func(params_obj)
    
    return {"audit_report": {"passed": result.passed, "messages": result.messages}}

def calculation_node(state: AgentState):
    print("--- Calculator: Running Deterministic Engine ---")
    params_dict = state["params"]
    model_type = state["model_type"]
    skill = SkillRegistry.get_skill(model_type)
    
    schema = skill["schema"]
    calc_func = skill["calculator"]
    
    params_obj = schema(**params_dict)
    
    result = calc_func(params_obj)
    return {"valuation_result": result}

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
