from typing import Any

from src.interface.schemas import AgentOutputArtifact, ArtifactReference
from src.utils.logger import get_logger

from ...state import AgentState
from .mappers import summarize_ta_for_preview

logger = get_logger(__name__)


def input_adapter(state: AgentState) -> dict[str, Any]:
    """Maps parent AgentState to TechnicalAnalysisState input."""
    logger.info(
        f"--- [TA Adapter] Mapping parent state to subgraph input for {state.get('ticker')} ---"
    )
    return {
        "ticker": state.get("ticker"),
        "intent_extraction": state.get("intent_extraction"),
        "technical_analysis": state.get("technical_analysis"),
    }


def output_adapter(sub_output: dict[str, Any]) -> dict[str, Any]:
    """Maps TechnicalAnalysisState output back to parent state updates."""
    logger.info("--- [TA Adapter] Mapping subgraph output back to parent state ---")

    ta_ctx = sub_output.get("technical_analysis", {})
    chart_id = ta_ctx.get("chart_data_id")

    # 1. Generate L2 Preview using Mapper
    preview = summarize_ta_for_preview(ta_ctx)

    # 2. Generate L3 Reference if chart data exists
    reference = None
    if chart_id:
        reference = ArtifactReference(
            artifact_id=chart_id,
            download_url=f"/api/artifacts/{chart_id}",
            type="ta_chart_data",
        )

    # 3. Construct Standardized AgentOutputArtifact
    direction = str(ta_ctx.get("signal", "N/A")).upper()
    optimal_d = ta_ctx.get("optimal_d", 0.0)

    artifact = AgentOutputArtifact(
        summary=f"Technical Analysis: {direction} (d={optimal_d:.2f})",
        preview=preview,
        reference=reference,
    )

    # 4. Inject artifact into context
    ta_ctx["artifact"] = artifact

    return {
        "technical_analysis": ta_ctx,
        "messages": sub_output.get("messages", []),
        "node_statuses": {"technical_analysis": "done"},
    }
