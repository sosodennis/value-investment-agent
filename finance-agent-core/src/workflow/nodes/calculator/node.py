"""
Calculator Node - Executes deterministic valuation calculations.

This is a simple wrapper around the SkillRegistry calculator functions.
"""

from typing import TYPE_CHECKING
from ...manager import SkillRegistry

if TYPE_CHECKING:
    from ...graph import AgentState


def calculation_node(state: "AgentState"):
    """
    Executes the deterministic valuation calculation.
    
    Args:
        state: Current agent state with params and model_type
        
    Returns:
        Updated state with valuation_result
    """
    print("--- Calculator: Running Deterministic Engine ---")
    
    params_dict = state["params"]
    model_type = state["model_type"]
    skill = SkillRegistry.get_skill(model_type)
    
    schema = skill["schema"]
    calc_func = skill["calculator"]
    
    params_obj = schema(**params_dict)
    
    result = calc_func(params_obj)
    return {"valuation_result": result}
