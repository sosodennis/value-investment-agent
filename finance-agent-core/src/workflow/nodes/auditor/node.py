"""
Auditor Node - Validates extracted parameters against business rules.

This is a simple wrapper around the SkillRegistry auditor functions.
"""

from langchain_core.messages import AIMessage
from langgraph.types import Command

from src.interface.schemas import AgentOutputArtifact
from src.utils.logger import get_logger

from ...manager import SkillRegistry
from ...schemas import AuditOutput
from ...state import AgentState
from .schemas import AuditorPreview

logger = get_logger(__name__)


def auditor_node(state: AgentState) -> Command:
    """
    Validates extracted parameters using skill-specific audit rules.
    """
    logger.info("--- Auditor: Checking parameters ---")
    logger.debug(f"DEBUG: Auditor State Keys: {list(state.keys())}")

    # Access Pydantic fields
    try:
        fundamental = state.get("fundamental_analysis", {})
        extraction_output = fundamental.get("extraction_output")
        if not extraction_output:
            logger.error("ERROR: Auditor found no extraction_output in state")
            raise ValueError("No extraction output found in state")

        params_dict = extraction_output.params
        model_type = fundamental.get("model_type")
        logger.debug(f"DEBUG: Check params for model={model_type}: {params_dict}")

        skill = SkillRegistry.get_skill(model_type)
        if not skill:
            logger.error(f"ERROR: Skill not found for {model_type}")
            raise ValueError(f"Skill not found regarding {model_type}")

        schema = skill["schema"]
        audit_func = skill["auditor"]
        logger.debug(f"DEBUG: Found skill schema={schema}, auditor={audit_func}")

        # Rehydrate Pydantic object
        logger.debug("DEBUG: Rehydrating Pydantic object...")
        params_obj = schema(**params_dict)
        logger.debug("DEBUG: Pydantic object created successfully.")

        logger.debug("DEBUG: Running audit function...")
        result = audit_func(params_obj)
        logger.debug(f"DEBUG: Audit result: {result}")

        return Command(
            update={
                "fundamental_analysis": {
                    "audit_output": AuditOutput(
                        passed=result.passed, messages=result.messages
                    )
                },
                "artifact": AgentOutputArtifact(
                    summary=f"Audit completed. Result: {'PASSED' if result.passed else 'FAILED'}. {len(result.messages)} findings identified.",
                    preview=AuditorPreview(
                        passed=result.passed,
                        finding_count=len(result.messages),
                        status="completed",
                    ).model_dump(),
                    reference=None,
                ),
                "node_statuses": {"auditor": "done", "approval": "running"},
            },
            goto="approval",
        )
    except Exception as e:
        logger.error(f"Audit Failed: {e}")
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
