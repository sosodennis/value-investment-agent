"""
Calculator Node - Executes deterministic valuation calculations.

This is a simple wrapper around the SkillRegistry calculator functions.
"""

from typing import TYPE_CHECKING
from ...manager import SkillRegistry
from langchain_core.messages import AIMessage

if TYPE_CHECKING:
    from ...graph import AgentState


from langgraph.types import Command
from langgraph.graph import END

def calculation_node(state: "AgentState") -> Command:
    """
    Executes the deterministic valuation calculation.
    """
    print("--- Calculator: Running Deterministic Engine ---")
    
    params_dict = state["params"]
    model_type = state["model_type"]
    skill = SkillRegistry.get_skill(model_type)
    
    schema = skill["schema"]
    calc_func = skill["calculator"]
    
    params_obj = schema(**params_dict)
    
    result = calc_func(params_obj)
    
    # Format the result nicely
    msg_content = f"### Valuation Complete\n\n**Model**: {model_type}\n**Result**: {result}"
    
    print("✅ Valuation Logic Complete. Returning result to Conversation.")
    
    return Command(
        update={
            "valuation_result": result,
            "messages": [AIMessage(content=msg_content)]
        },
        goto=END
    )
