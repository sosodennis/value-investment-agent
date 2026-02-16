from __future__ import annotations

from src.shared.kernel.types import JSONObject


def format_news_preview(view_model: JSONObject) -> JSONObject:
    score = float(view_model.get("sentiment_score", 0.0) or 0.0)
    if score > 0.1:
        emoji = "📈"
    elif score < -0.1:
        emoji = "📉"
    else:
        emoji = "⚖️"

    status = str(view_model.get("status", "processing"))
    status_label = (
        "完成" if status == "success" else "錯誤" if status == "error" else "處理中"
    )
    sentiment_summary = str(view_model.get("sentiment_summary", "neutral"))
    article_count = int(view_model.get("article_count", 0) or 0)
    top_headlines_raw = view_model.get("top_headlines", [])
    top_headlines = top_headlines_raw[:3] if isinstance(top_headlines_raw, list) else []

    return {
        "status_label": status_label,
        "sentiment_display": f"{emoji} {sentiment_summary} ({score:.2f})",
        "article_count_display": f"分析了 {article_count} 篇新聞",
        "top_headlines": top_headlines,
    }
