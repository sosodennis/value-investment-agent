from typing import Any

from src.interface.schemas import AgentOutputArtifact, ArtifactReference
from src.utils.logger import get_logger

from ...state import AgentState
from .mappers import summarize_debate_for_preview

logger = get_logger(__name__)


def input_adapter(state: AgentState) -> dict[str, Any]:
    """Maps parent AgentState to DebateState input."""
    logger.info("--- [Debate Adapter] Mapping parent state to subgraph input ---")
    fundamental = state.get("fundamental_analysis", {})
    return {
        "ticker": state.get("ticker"),
        "intent_extraction": state.get("intent_extraction"),
        "fundamental_analysis": fundamental,
        "financial_news_research": state.get("financial_news_research"),
        "technical_analysis": state.get("technical_analysis"),
        "debate": state.get("debate"),
        "messages": state.get("messages", []),
        "model_type": fundamental.get("model_type"),
    }


def output_adapter(sub_output: dict[str, Any]) -> dict[str, Any]:
    """Maps DebateState output back to parent state updates."""
    logger.info("--- [Debate Adapter] Mapping subgraph output back to parent state ---")

    debate_ctx = sub_output.get("debate", {})
    transcript_id = debate_ctx.get("transcript_id")

    # Generate Preview (L2)
    preview = summarize_debate_for_preview(debate_ctx)

    # Create Reference (L3)
    reference = None
    if transcript_id:
        reference = ArtifactReference(
            artifact_id=transcript_id,
            download_url=f"/api/artifacts/{transcript_id}",
            type="debate_transcript",
        )

    # Generate AgentOutputArtifact for the interface
    artifact = AgentOutputArtifact(
        summary=preview.get("verdict_display", "Analysis Complete"),
        preview=preview,
        reference=reference,
    )

    # Carry forward model_type for next nodes
    messages = sub_output.get("messages", [])
    model_type = sub_output.get("model_type")

    # If final_verdict is available, we can also extract model_type from it
    # to maintain compatibility with Executor agent expectation
    if debate_ctx.get("final_verdict"):
        # The verdict node already mapped metrics, but if we need to refine model_type:
        # (This logic might vary depending on how Executor uses it)
        pass

    # Update FundamentalAnalysisContext with the decided model_type if any
    fundamental_update = {}
    if model_type:
        fundamental_update["model_type"] = model_type

    # Attach the artifact to the debate context update
    debate_ctx["artifact"] = artifact

    return {
        "debate": debate_ctx,
        "fundamental_analysis": fundamental_update,
        "messages": messages,
        "node_statuses": {"debate": "done"},
    }
