from __future__ import annotations

from src.agents.news.domain.models import NewsAggregationResult
from src.shared.kernel.types import JSONObject


def build_search_progress_preview(
    *,
    article_count: int,
    cleaned_results: list[JSONObject],
) -> JSONObject:
    return {
        "status_label": "搜尋完成",
        "sentiment_display": "⚖️ PENDING ANALYSIS",
        "article_count_display": f"找到 {article_count} 篇新聞",
        "top_headlines": [r.get("title") for r in cleaned_results[:3]],
    }


def build_news_report_payload(
    *,
    ticker: str,
    news_items: list[JSONObject],
    aggregation: NewsAggregationResult,
) -> JSONObject:
    return {
        "ticker": ticker,
        "news_items": news_items,
        "overall_sentiment": aggregation.sentiment_label,
        "sentiment_score": aggregation.weighted_score,
        "key_themes": aggregation.key_themes,
    }
