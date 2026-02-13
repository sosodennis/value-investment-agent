from __future__ import annotations

from src.common.types import JSONObject


def summarize_intent_for_preview(ctx: JSONObject) -> JSONObject:
    status = ctx.get("status")
    profile = ctx.get("company_profile") or {}

    return {
        "ticker": ctx.get("resolved_ticker"),
        "company_name": profile.get("name"),
        "status_label": _get_status_label(status if isinstance(status, str) else None),
        "exchange": profile.get("exchange"),
    }


def _get_status_label(status: str | None) -> str:
    mapping = {
        "extraction": "解析意圖中...",
        "searching": "搜尋股票代號中...",
        "deciding": "正在確認結果...",
        "clarifying": "等待訊息輸入...",
        "resolved": "已確認標的",
    }
    return mapping.get(status, "準備中" if not status else f"狀態: {status}")
