"""
Auditor Node - Validates extracted parameters against business rules.

This is a simple wrapper around the SkillRegistry auditor functions.
"""

from typing import TYPE_CHECKING
from ...manager import SkillRegistry

if TYPE_CHECKING:
    from ...graph import AgentState


def auditor_node(state: "AgentState"):
    """
    Validates extracted parameters using skill-specific audit rules.
    
    Args:
        state: Current agent state with params and model_type
        
    Returns:
        Updated state with audit_report containing passed status and messages
    """
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
