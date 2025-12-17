"""
Executor Node - Extracts valuation parameters from financial data.

In production, this would use LLM to extract parameters from 10-K filings,
financial statements, and other sources.
"""

from typing import TYPE_CHECKING
from ...manager import SkillRegistry
from .tools import generate_mock_saas_data, generate_mock_bank_data

if TYPE_CHECKING:
    from ...graph import AgentState


def executor_node(state: "AgentState"):
    """
    Extracts valuation parameters for the selected model type.
    
    Args:
        state: Current agent state with ticker and model_type
        
    Returns:
        Updated state with extracted params (validated against schema)
        
    Note:
        Currently generates mock data. In production, this would use
        LLM extraction with prompts from prompts.py and tools from tools.py
    """
    print(f"--- Executor: Extracting parameters for {state['model_type']} ---")
    
    skill = SkillRegistry.get_skill(state["model_type"])
    if not skill:
        raise ValueError(f"Unknown model type: {state['model_type']}")
        
    schema = skill["schema"]
    
    # MOCK DATA GENERATION
    if state['model_type'] == 'saas':
        mock_data = generate_mock_saas_data(state["ticker"])
    elif state['model_type'] == 'bank':
        mock_data = generate_mock_bank_data(state["ticker"])
    else:
        raise ValueError(f"Unsupported model type: {state['model_type']}")
    
    # Validate structure via Pydantic (ensure it matches schema)
    try:
        validated = schema(**mock_data)
        return {"params": validated.model_dump()}
    except Exception as e:
        print(f"Extraction Failed: {e}")
        return {}
