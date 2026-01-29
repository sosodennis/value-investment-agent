"""
Mapper layer for Financial News Research agent.
Transforms internal state into lightweight preview data for UI rendering.
"""


def summarize_news_for_preview(ctx: dict, news_items: list[dict] | None = None) -> dict:
    """
    Generate preview data for Financial News UI (<1KB).

    Args:
        ctx: FinancialNewsContext dictionary containing metadata
        news_items: Optional list of news item summaries (not full content)

    Returns:
        Dictionary with preview data for immediate UI rendering
    """
    # Defensive programming: ensure score is float, handle None
    raw_score = ctx.get("sentiment_score", 0.0)
    score = float(raw_score or 0.0)  # Convert None to 0.0
    display_score = f"{score:.2f}"

    # Determine emoji based on score
    if score > 0.1:
        emoji = "📈"
    elif score < -0.1:
        emoji = "📉"
    else:
        emoji = "⚖️"

    # Get status
    status = ctx.get("status", "processing")
    status_label = (
        "完成" if status == "success" else "錯誤" if status == "error" else "處理中"
    )

    # Get sentiment summary with fallback
    sentiment_summary = ctx.get("sentiment_summary", "neutral")

    # Get article count
    article_count = ctx.get("article_count", 0)

    # Extract top 3 headlines
    top_headlines = []
    if news_items:
        for item in news_items[:3]:
            if isinstance(item, dict):
                title = item.get("title", "")
                if title:
                    top_headlines.append(title)
    else:
        # Fallback to headlines stored in context
        top_headlines = ctx.get("top_headlines", [])[:3]

    return {
        "status_label": status_label,
        "sentiment_display": f"{emoji} {sentiment_summary} ({display_score})",
        "article_count_display": f"分析了 {article_count} 篇新聞",
        "top_headlines": top_headlines,
    }
