from __future__ import annotations

from src.agents.news.domain.aggregation.contracts import NewsAggregationResult


def build_news_summary_message(*, ticker: str, result: NewsAggregationResult) -> str:
    return (
        f"### News Research: {ticker}\n\n"
        f"**Overall Sentiment:** {result.sentiment_label.upper()} ({result.weighted_score})\n\n"
        f"**Analysis Summaries:**\n{result.summary_text}\n\n"
        f"**Themes:** {', '.join(result.key_themes) or 'N/A'}"
    )
