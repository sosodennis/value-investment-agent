from __future__ import annotations

from src.agents.news.domain.models import NewsAggregationResult
from src.common.types import JSONObject


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
