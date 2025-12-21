"""
Executor Node - Extracts valuation parameters from financial data.

In production, this would use LLM to extract parameters from 10-K filings,
financial statements, and other sources.
"""

from typing import TYPE_CHECKING
from ...manager import SkillRegistry
from .tools import generate_mock_saas_data, generate_mock_bank_data

from ...state import AgentState
from ...schemas import ExtractionOutput

from langgraph.types import Command
from langgraph.graph import END

def executor_node(state: AgentState) -> Command:
    """
    Extracts valuation parameters for the selected model type.
    """
    print(f"--- Executor: Extracting parameters for {state.model_type} ---")
    
    skill = SkillRegistry.get_skill(state.model_type)
    if not skill:
        raise ValueError(f"Unknown model type: {state.model_type}")
        
    schema = skill["schema"]
    
    # MOCK DATA GENERATION
    if state.model_type == 'saas':
        mock_data = generate_mock_saas_data(state.ticker)
    elif state.model_type == 'bank':
        mock_data = generate_mock_bank_data(state.ticker)
    else:
        raise ValueError(f"Unsupported model type: {state.model_type}")
    
    # Validate structure via Pydantic
    try:
        validated = schema(**mock_data)
        # Wrap in ExtractionOutput
        output = ExtractionOutput(params=validated.model_dump())
        return Command(
            update={"extraction_output": output},
            goto="auditor"
        )
    except Exception as e:
        print(f"Extraction Failed: {e}")
        return Command(goto=END) # Fallback if extraction fails completely
