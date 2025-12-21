"""
Auditor Node - Validates extracted parameters against business rules.

This is a simple wrapper around the SkillRegistry auditor functions.
"""

from ...state import AgentState
from ...schemas import AuditOutput
from ...manager import SkillRegistry

from langgraph.types import Command

def auditor_node(state: AgentState) -> Command:
    """
    Validates extracted parameters using skill-specific audit rules.
    """
    print("--- Auditor: Checking parameters ---")
    
    # Access Pydantic fields
    if not state.extraction_output:
        raise ValueError("No extraction output found in state")
        
    params_dict = state.extraction_output.params
    model_type = state.model_type
    skill = SkillRegistry.get_skill(model_type)
    
    schema = skill["schema"]
    audit_func = skill["auditor"]
    
    # Rehydrate Pydantic object
    params_obj = schema(**params_dict)
    
    result = audit_func(params_obj)
    
    return Command(
        update={"audit_output": AuditOutput(passed=result.passed, messages=result.messages)},
        goto="approval"
    )
