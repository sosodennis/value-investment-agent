from typing import Any

from src.utils.logger import get_logger

from ...state import AgentState

logger = get_logger(__name__)


def input_adapter(state: AgentState) -> dict[str, Any]:
    """將父圖狀態轉換為子圖輸入"""
    logger.info(
        f"--- [FA Adapter] Mapping parent state to subgraph input for {state.ticker} ---"
    )
    return {
        "ticker": state.ticker,
        "intent_extraction": state.intent_extraction,
        "fundamental": state.fundamental,
        # internal_progress, current_node 會由子圖自己初始化
    }


def map_model_to_skill(model_name: str | None) -> str:
    """
    Maps a valuation model name or enum value to a valid SkillRegistry key.

    Currently supports:
    - 'bank' (for DDM/Bank models)
    - 'saas' (default, for all DCF/Growth models using FCFF engine)
    """
    if not model_name:
        return "saas"

    name_lower = str(model_name).lower()
    if any(x in name_lower for x in ["bank", "ddm"]):
        return "bank"

    return "saas"


def output_adapter(sub_output: dict[str, Any]) -> dict[str, Any]:
    """將子圖輸出轉換為父圖更新"""
    logger.info("--- [FA Adapter] Mapping subgraph output back to parent state ---")
    # 從子圖結果中提取關鍵數據
    fundamental_ctx = sub_output.get("fundamental")
    raw_model = None

    if fundamental_ctx and fundamental_ctx.get("analysis_output"):
        raw_model = fundamental_ctx["analysis_output"].get("model_type")

    model_type = map_model_to_skill(raw_model)

    return {
        "fundamental": fundamental_ctx,
        "ticker": sub_output.get("ticker"),
        "model_type": model_type,
        "node_statuses": {"fundamental_analysis": "done"},
    }
