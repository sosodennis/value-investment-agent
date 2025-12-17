"""
Planner Node - Determines which valuation model to use.

In production, this would use an LLM to analyze the ticker/company description
and decide between 'saas', 'bank', or other model types.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...graph import AgentState


def planner_node(state: "AgentState"):
    """
    Determines the appropriate valuation model type for the given ticker.
    
    Args:
        state: Current agent state containing ticker and model_type
        
    Returns:
        Updated state with confirmed model_type
        
    Note:
        Currently uses the model_type passed in state. In production,
        this would use LLM analysis with prompts from prompts.py
    """
    # In a real implementation, LLM decides model_type based on ticker description.
    # Here we assume it's passed in or use heuristic.
    print(f"--- Planner: Selected {state['model_type']} for {state['ticker']} ---")
    return {"model_type": state["model_type"]}
