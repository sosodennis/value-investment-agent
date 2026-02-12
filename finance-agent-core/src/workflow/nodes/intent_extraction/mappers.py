"""
Mappers for Intent Extraction agent.
Transforms internal state/context into UI-ready preview data.
"""

from src.common.types import JSONObject


def summarize_intent_for_preview(ctx: JSONObject) -> JSONObject:
    """
    Transform IntentExtractionContext into a lightweight preview for the UI.

    Args:
        ctx: The intent_extraction context dictionary (from State)

    Returns:
        A dictionary matching IntentExtractionPreview schema
    """
    status = ctx.get("status")
    profile = ctx.get("company_profile") or {}

    return {
        "ticker": ctx.get("resolved_ticker"),
        "company_name": profile.get("name"),
        "status_label": _get_status_label(status),
        "exchange": profile.get("exchange"),
    }


def _get_status_label(status: str | None) -> str:
    """Map internal status to human-readable UI label."""
    mapping = {
        "extraction": "解析意圖中...",
        "searching": "搜尋股票代號中...",
        "deciding": "正在確認結果...",
        "clarifying": "等待訊息輸入...",
        "resolved": "已確認標的",
    }
    return mapping.get(status, "準備中" if not status else f"狀態: {status}")
