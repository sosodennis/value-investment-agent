"""
Auditor Node - Validates extracted parameters against business rules.

This is a simple wrapper around the SkillRegistry auditor functions.
"""

from langchain_core.messages import AIMessage
from langgraph.types import Command

from ...manager import SkillRegistry
from ...schemas import AuditOutput
from ...state import AgentState


def auditor_node(state: AgentState) -> Command:
    """
    Validates extracted parameters using skill-specific audit rules.
    """
    print("--- Auditor: Checking parameters ---")
    print(f"DEBUG: Auditor State Keys: {state.model_dump().keys()}")

    # Access Pydantic fields
    try:
        if not state.extraction_output:
            print("ERROR: Auditor found no extraction_output in state")
            raise ValueError("No extraction output found in state")

        params_dict = state.extraction_output.params
        model_type = state.model_type
        print(f"DEBUG: Check params for model={model_type}: {params_dict}")

        skill = SkillRegistry.get_skill(model_type)
        if not skill:
            print(f"ERROR: Skill not found for {model_type}")
            raise ValueError(f"Skill not found regarding {model_type}")

        schema = skill["schema"]
        audit_func = skill["auditor"]
        print(f"DEBUG: Found skill schema={schema}, auditor={audit_func}")

        # Rehydrate Pydantic object
        print("DEBUG: Rehydrating Pydantic object...")
        params_obj = schema(**params_dict)
        print("DEBUG: Pydantic object created successfully.")

        print("DEBUG: Running audit function...")
        result = audit_func(params_obj)
        print(f"DEBUG: Audit result: {result}")

        return Command(
            update={
                "messages": [
                    AIMessage(
                        content=f"Audit completed. Result: {'PASSED' if result.passed else 'FAILED'}. {len(result.messages)} findings identified.",
                        additional_kwargs={"agent_id": "auditor"},
                    )
                ],
                "audit_output": AuditOutput(
                    passed=result.passed, messages=result.messages
                ),
                "node_statuses": {"auditor": "done", "approval": "running"},
            },
            goto="approval",
        )
    except Exception as e:
        print(f"Audit Failed: {e}")
        from langgraph.graph import END

        return Command(
            update={
                "messages": [
                    AIMessage(
                        content=f"Audit failed: {e}",
                        additional_kwargs={"agent_id": "auditor"},
                    )
                ],
                "node_statuses": {"auditor": "error"},
            },
            goto=END,
        )
