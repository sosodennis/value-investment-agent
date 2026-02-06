"""
Auditor Node - Validates extracted parameters against business rules.
"""

from langgraph.graph import END
from langgraph.types import Command

from src.common.tools.logger import get_logger
from src.interface.schemas import AgentOutputArtifact

from ...manager import SkillRegistry
from ...schemas import AuditOutput
from .mappers import summarize_auditor_for_preview
from .subgraph_state import AuditorState

logger = get_logger(__name__)


def auditor_node(state: AuditorState) -> Command:
    """
    Validates extracted parameters using skill-specific audit rules.
    """
    logger.info("--- Auditor: Checking parameters ---")

    try:
        fundamental = state.get("fundamental_analysis", {})
        extraction_output = fundamental.get("extraction_output")
        if not extraction_output:
            raise ValueError("No extraction output found in state")

        params_dict = extraction_output.params
        model_type = fundamental.get("model_type")

        skill = SkillRegistry.get_skill(model_type)
        if not skill:
            raise ValueError(f"Skill not found regarding {model_type}")

        schema = skill["schema"]
        audit_func = skill["auditor"]

        # Rehydrate Pydantic object
        params_obj = schema(**params_dict)

        result = audit_func(params_obj)

        audit_output = AuditOutput(passed=result.passed, messages=result.messages)
        preview = summarize_auditor_for_preview(audit_output)
        artifact = AgentOutputArtifact(
            summary=f"Audit completed. Result: {'PASSED' if result.passed else 'FAILED'}. {len(result.messages)} findings identified.",
            preview=preview,
            reference=None,
        )

        fa_update = fundamental.copy()
        fa_update["audit_output"] = audit_output
        fa_update["artifact"] = artifact

        return Command(
            update={
                "fundamental_analysis": fa_update,
                "current_node": "auditor",
                "node_statuses": {"auditor": "done"},
                "artifact": artifact,
            },
            goto=END,
        )
    except Exception as e:
        logger.error(f"Audit Failed: {e}", exc_info=True)
        return Command(
            update={
                "error_logs": [
                    {
                        "node": "auditor",
                        "error": str(e),
                        "severity": "error",
                    }
                ],
                "node_statuses": {"auditor": "error"},
            },
            goto=END,
        )
