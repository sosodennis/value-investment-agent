"""
Shared state definitions for the workflow graph.
Refactored to comply with Engineering Charter v3.1 (TypedDict + Artifact Store).
"""

from collections.abc import Mapping
from typing import Annotated, NotRequired

from langchain_core.messages import AnyMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict

from src.shared.kernel.types import AgentOutputArtifactPayload, JSONObject

# 注意：我們不再需要從 pydantic 導入 BaseModel 用於 State
# 也不再需要 AgentOutputArtifact，因為它只存在於 Adapter 層


def merge_dict(a: dict, b: dict) -> dict:
    """Simple dict merge reducer."""
    if a is None:
        return b
    if b is None:
        return a
    return {**a, **b}


def last_value(a: object | None, b: object | None) -> object | None:
    """Reducer that keeps the last non-None value."""
    return b if b is not None else a


def append_logs(a: list[dict], b: list[dict]) -> list[dict]:
    """Simple list-append reducer for logs."""
    return (a or []) + (b or [])


def _is_pandas_frame_or_series(value: object) -> bool:
    if value is None:
        return False
    value_type = type(value)
    module = getattr(value_type, "__module__", "")
    name = getattr(value_type, "__name__", "")
    if module == "pandas.core.frame" and name == "DataFrame":
        return True
    if module == "pandas.core.series" and name == "Series":
        return True
    return False


def find_state_hygiene_violations(
    value: object,
    *,
    path: str = "",
) -> list[str]:
    violations: list[str] = []
    if _is_pandas_frame_or_series(value):
        violations.append(path or "<root>")
        return violations

    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key)
            next_path = f"{path}.{key_text}" if path else key_text
            violations.extend(find_state_hygiene_violations(item, path=next_path))
        return violations

    if isinstance(value, list | tuple | set):
        for idx, item in enumerate(value):
            next_path = f"{path}[{idx}]" if path else f"[{idx}]"
            violations.extend(find_state_hygiene_violations(item, path=next_path))
        return violations

    return violations


# --- Context Definitions (TypedDict) ---


class IntentExtractionContext(TypedDict):
    """Context for intent extraction workflow."""

    # 使用 NotRequired 標記可選字段
    extracted_intent: NotRequired[JSONObject | None]
    ticker_candidates: NotRequired[list[JSONObject] | None]
    resolved_ticker: NotRequired[str | None]
    company_profile: NotRequired[JSONObject | None]
    status: NotRequired[str | None]  # extraction, searching, deciding, resolved
    artifact: NotRequired[AgentOutputArtifactPayload | None]


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

    artifact: NotRequired[AgentOutputArtifactPayload | None]


class FundamentalAnalysisContext(TypedDict):
    """Context for fundamental analysis workflow."""

    model_type: NotRequired[str | None]  # e.g., saas, bank
    financial_reports_artifact_id: NotRequired[str | None]
    artifact: NotRequired[AgentOutputArtifactPayload | None]


class FinancialNewsContext(TypedDict):
    """
    Context for financial news workflow.
    Refactored per Engineering Charter v3.1 - Metadata Only.
    """

    search_artifact_id: NotRequired[str]  # Pointer to raw/formatted search results
    selection_artifact_id: NotRequired[str]  # Pointer to selected indices/items
    news_items_artifact_id: NotRequired[
        str
    ]  # Pointer to list of news items (dictionaries)
    report_id: NotRequired[str | None]
    artifact: NotRequired[AgentOutputArtifactPayload | None]


class TechnicalAnalysisContext(TypedDict):
    """Context for technical analysis workflow."""

    latest_price: NotRequired[float | None]
    optimal_d: NotRequired[float | None]
    z_score_latest: NotRequired[float | None]
    signal: NotRequired[str | None]  # "BUY", "SELL", "HOLD"
    statistical_strength: NotRequired[str | None]  # e.g. "high"
    risk_level: NotRequired[str | None]
    llm_interpretation: NotRequired[str | None]
    semantic_tags: NotRequired[list[str] | None]
    memory_strength: NotRequired[str | None]
    is_degraded: NotRequired[bool | None]
    degraded_reasons: NotRequired[list[str] | None]

    window_length: NotRequired[int | None]
    adf_statistic: NotRequired[float | None]
    adf_pvalue: NotRequired[float | None]
    bollinger: NotRequired[JSONObject | None]
    statistical_strength_val: NotRequired[float | None]
    macd: NotRequired[JSONObject | None]
    obv: NotRequired[JSONObject | None]

    price_artifact_id: NotRequired[str | None]
    chart_data_id: NotRequired[str | None]
    timeseries_bundle_id: NotRequired[str | None]
    indicator_series_id: NotRequired[str | None]
    alerts_id: NotRequired[str | None]
    feature_pack_id: NotRequired[str | None]
    pattern_pack_id: NotRequired[str | None]
    fusion_report_id: NotRequired[str | None]
    verification_report_id: NotRequired[str | None]
    artifact: NotRequired[AgentOutputArtifactPayload | None]


# --- Root State ---


class AgentState(TypedDict):
    """
    Root Agent State.
    Fully converted to TypedDict.
    """

    # Global Shared State
    user_query: Annotated[str | None, last_value]

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
    internal_progress: Annotated[dict[str, str], merge_dict]

    # Error logging
    error_logs: Annotated[list[dict], append_logs]
