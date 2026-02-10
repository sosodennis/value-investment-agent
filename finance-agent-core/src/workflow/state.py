"""
Shared state definitions for the workflow graph.
Refactored to comply with Engineering Charter v3.1 (TypedDict + Artifact Store).
"""

from typing import Annotated, Any, NotRequired

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict

from src.interface.schemas import AgentOutputArtifact

# 注意：我們不再需要從 pydantic 導入 BaseModel 用於 State
# 也不再需要 AgentOutputArtifact，因為它只存在於 Adapter 層


def merge_dict(a: dict, b: dict) -> dict:
    """Simple dict merge reducer."""
    if a is None:
        return b
    if b is None:
        return a
    return {**a, **b}


def last_value(a: Any | None, b: Any | None) -> Any | None:
    """Reducer that keeps the last non-None value."""
    return b if b is not None else a


def append_logs(a: list[dict], b: list[dict]) -> list[dict]:
    """Simple list-append reducer for logs."""
    return (a or []) + (b or [])


# --- Context Definitions (TypedDict) ---


class IntentExtractionContext(TypedDict):
    """Context for intent extraction workflow."""

    # 使用 NotRequired 標記可選字段
    extracted_intent: NotRequired[dict[str, Any] | None]
    ticker_candidates: NotRequired[list[Any] | None]
    resolved_ticker: NotRequired[str | None]
    company_profile: NotRequired[dict[str, Any] | None]
    status: NotRequired[str | None]  # extraction, searching, deciding, resolved
    artifact: NotRequired[AgentOutputArtifact | None]


class DebateContext(TypedDict):
    """
    Context for debate workflow.
    Refactored per Engineering Charter v3.1 - Metadata & References only.
    """

    status: NotRequired[str | None]
    current_round: NotRequired[int]

    # [L2 Data] Key conclusions for UI and next nodes
    final_verdict: NotRequired[str | None]  # "LONG", "SHORT", etc.
    kelly_confidence: NotRequired[float | None]
    winning_thesis: NotRequired[str | None]
    primary_catalyst: NotRequired[str | None]
    primary_risk: NotRequired[str | None]

    # [L3 Pointer] Pointer to full debate transcript in Artifact Store
    transcript_id: NotRequired[str | None]

    # [L3 Pointer] Pointer to extracted facts in Artifact Store
    facts_artifact_id: NotRequired[str | None]
    facts_hash: NotRequired[str | None]
    facts_summary: NotRequired[dict[str, int] | None]

    artifact: NotRequired[AgentOutputArtifact | None]


class FundamentalAnalysisContext(TypedDict):
    """Context for fundamental analysis workflow."""

    status: NotRequired[str | None]
    approved: NotRequired[bool | None]
    model_type: NotRequired[str | None]  # e.g., saas, bank

    # [L2 Data] 關鍵業務指標 (Source of Truth)
    valuation_score: NotRequired[float | None]
    valuation_summary: NotRequired[str | None]

    # [L3 Pointer] 指向 Artifact Store 的 ID
    latest_report_id: NotRequired[str | None]

    # 下面這些複雜對象建議未來也轉為 Artifact ID 或精簡字典
    extraction_output: NotRequired[dict | None]
    audit_output: NotRequired[dict | None]
    calculation_output: NotRequired[dict | None]
    artifact: NotRequired[AgentOutputArtifact | None]


class FinancialNewsContext(TypedDict):
    """
    Context for financial news workflow.
    Refactored per Engineering Charter v3.1 - Metadata Only.
    """

    status: NotRequired[str]  # "success" | "error" | "processing"

    # [L2 Data] 用於 Adapter 生成 Preview
    sentiment_summary: NotRequired[str]  # "bullish" | "bearish" | "neutral"
    sentiment_score: NotRequired[float]  # -1.0 to 1.0
    article_count: NotRequired[int]

    # [L3 Pointer] 指向 Artifact Store 的 ID
    search_artifact_id: NotRequired[str]  # Pointer to raw/formatted search results
    selection_artifact_id: NotRequired[str]  # Pointer to selected indices/items
    news_items_artifact_id: NotRequired[
        str
    ]  # Pointer to list of news items (dictionaries)
    report_id: NotRequired[str]

    error_message: NotRequired[str]
    artifact: NotRequired[AgentOutputArtifact | None]


class TechnicalAnalysisContext(TypedDict):
    """Context for technical analysis workflow."""

    status: NotRequired[str | None]

    # [L2 Data]
    latest_price: NotRequired[float | None]
    optimal_d: NotRequired[float | None]
    z_score_latest: NotRequired[float | None]
    signal: NotRequired[str | None]  # "BUY", "SELL", "HOLD"
    statistical_strength: NotRequired[str | None]
    signals: NotRequired[dict[str, str] | None]  # e.g. {"rsi": "buy"}

    # [L3 Pointer] 指向圖表數據或回測報告
    price_artifact_id: NotRequired[str | None]
    chart_data_id: NotRequired[str | None]
    artifact: NotRequired[AgentOutputArtifact | None]


# --- Root State ---


class AgentState(TypedDict):
    """
    Root Agent State.
    Fully converted to TypedDict.
    """

    # Global Shared State
    user_query: Annotated[str | None, last_value]
    ticker: Annotated[str | None, last_value]

    # Global Conversation History
    messages: Annotated[list[AnyMessage], add_messages]

    # Sub-Agent Contexts
    # 使用 merge_dict 允許子圖進行部分更新 (Partial Updates)
    intent_extraction: Annotated[IntentExtractionContext, merge_dict]

    fundamental_analysis: Annotated[FundamentalAnalysisContext, merge_dict]

    financial_news_research: Annotated[FinancialNewsContext, merge_dict]

    technical_analysis: Annotated[TechnicalAnalysisContext, merge_dict]

    debate: Annotated[DebateContext, merge_dict]

    # Dashboard tracking
    node_statuses: Annotated[dict[str, str], merge_dict]
    current_node: Annotated[str | None, last_value]

    # Error logging
    error_logs: Annotated[list[dict], append_logs]
