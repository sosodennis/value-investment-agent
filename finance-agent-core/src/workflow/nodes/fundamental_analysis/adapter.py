from typing import Any

from src.interface.schemas import AgentOutputArtifact, ArtifactReference
from src.utils.logger import get_logger

from ...state import AgentState
from .mappers import summarize_fundamental_for_preview

logger = get_logger(__name__)


def input_adapter(state: AgentState) -> dict[str, Any]:
    """將父圖狀態轉換為子圖輸入"""
    logger.info(
        f"--- [FA Adapter] Mapping parent state to subgraph input for {state['ticker']} ---"
    )
    return {
        "ticker": state["ticker"],
        "intent_extraction": state["intent_extraction"],
        "fundamental_analysis": state["fundamental_analysis"],
    }


def map_model_to_skill(model_name: str | None) -> str:
    """Maps a valuation model name to a skill key."""
    if not model_name:
        return "saas"
    name_lower = str(model_name).lower()
    if any(x in name_lower for x in ["bank", "ddm"]):
        return "bank"
    return "saas"


def output_adapter(sub_output: dict[str, Any]) -> dict[str, Any]:
    """將子圖輸出轉換為父圖更新"""
    logger.info("--- [FA Adapter] Mapping subgraph output back to parent state ---")

    # 1. Get the context from subgraph output
    fundamental_ctx = sub_output.get("fundamental_analysis", {})

    # 2. Extract metadata for mapping
    raw_model = sub_output.get("model_type")
    if not raw_model and isinstance(fundamental_ctx, dict):
        raw_model = fundamental_ctx.get("model_type")

    model_type = map_model_to_skill(raw_model)
    fundamental_ctx["model_type"] = model_type

    # 3. Generate Preview and Reference (Charter v3.1)
    try:
        financial_reports = fundamental_ctx.get("financial_reports", [])

        # Add extra info for mapper
        mapper_ctx = fundamental_ctx.copy()
        mapper_ctx["ticker"] = sub_output.get("ticker", "UNKNOWN")

        # Get company info from intent_extraction if available
        intent_ctx = sub_output.get("intent_extraction", {})
        if intent_ctx and "company_profile" in intent_ctx:
            profile = intent_ctx["company_profile"]
            mapper_ctx["company_name"] = profile.get("name")
            mapper_ctx["sector"] = profile.get("sector")
            mapper_ctx["industry"] = profile.get("industry")

        preview = summarize_fundamental_for_preview(mapper_ctx, financial_reports)

        report_id = fundamental_ctx.get("latest_report_id")
        reference = None
        if report_id:
            reference = ArtifactReference(
                artifact_id=report_id,
                download_url=f"/api/artifacts/{report_id}",
                type="financial_reports",
            )

        artifact = AgentOutputArtifact(
            summary=f"基本面分析: {preview['company_name']} ({preview['selected_model']})",
            preview=preview,
            reference=reference,
        )

        fundamental_ctx["artifact"] = artifact
        logger.info(
            f"✅ [FA Adapter] Created preview and reference for report {report_id}"
        )

    except Exception as e:
        logger.error(f"❌ [FA Adapter] Failed to generate preview: {e}")

    return {
        "fundamental_analysis": fundamental_ctx,
        "ticker": sub_output.get("ticker"),
        "node_statuses": {"fundamental_analysis": "done"},
    }
