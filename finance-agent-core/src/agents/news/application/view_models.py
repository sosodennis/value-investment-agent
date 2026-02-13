from __future__ import annotations

from src.common.types import JSONObject


def derive_news_preview_view_model(
    ctx: JSONObject,
    news_items: list[JSONObject] | None = None,
) -> JSONObject:
    raw_score = ctx.get("sentiment_score", 0.0)
    score = float(raw_score or 0.0)

    status = ctx.get("status", "processing")
    sentiment_summary = str(ctx.get("sentiment_summary", "neutral"))
    article_count = int(ctx.get("article_count", 0) or 0)

    top_headlines: list[str] = []
    if news_items:
        for item in news_items[:3]:
            title = item.get("title")
            if isinstance(title, str) and title:
                top_headlines.append(title)
    else:
        headlines = ctx.get("top_headlines", [])
        if isinstance(headlines, list):
            top_headlines = [
                str(headline) for headline in headlines[:3] if isinstance(headline, str)
            ]

    return {
        "status": status,
        "sentiment_summary": sentiment_summary,
        "sentiment_score": score,
        "article_count": article_count,
        "top_headlines": top_headlines,
    }
