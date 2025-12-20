"""
Auditor Node - Validates extracted parameters against business rules.

This is a simple wrapper around the SkillRegistry auditor functions.
"""

from typing import TYPE_CHECKING
from ...manager import SkillRegistry

if TYPE_CHECKING:
    from ...graph import AgentState


from langgraph.types import Command

def auditor_node(state: "AgentState") -> Command:
    """
    Validates extracted parameters using skill-specific audit rules.
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
    
    return Command(
        update={"audit_report": {"passed": result.passed, "messages": result.messages}},
        goto="approval"
    )
