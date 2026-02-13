from __future__ import annotations

from src.agents.news.domain.entities import NewsItemEntity
from src.agents.news.domain.models import NewsAggregationResult


def aggregate_news_items(
    news_items: list[NewsItemEntity], *, ticker: str
) -> NewsAggregationResult:
    weighted_score = 0.0
    sentiment_label = "neutral"
    summary_text = ""
    key_themes: list[str] = []

    if news_items:
        total_weight = 0.0
        weighted_score_sum = 0.0
        themes: set[str] = set()
        summaries: list[str] = []

        for item in news_items:
            analysis = item.analysis
            if analysis is None:
                continue
            weight = item.source.reliability_score if item.source is not None else 0.5
            total_weight += weight
            weighted_score_sum += analysis.sentiment_score * weight

            if analysis.key_event:
                themes.add(analysis.key_event)

            summaries.append(
                f"- {analysis.summary} ({analysis.key_facts_count} key facts)"
            )

        weighted_score = weighted_score_sum / total_weight if total_weight > 0 else 0.0
        if weighted_score > 0.3:
            sentiment_label = "bullish"
        elif weighted_score < -0.3:
            sentiment_label = "bearish"

        summary_text = "\n".join(summaries)
        key_themes = list(themes)

    top_headlines = [
        item.title
        for item in news_items[:3]
        if isinstance(item.title, str) and item.title
    ]
    return NewsAggregationResult(
        sentiment_label=sentiment_label,
        weighted_score=round(weighted_score, 2),
        key_themes=key_themes,
        summary_text=summary_text,
        top_headlines=top_headlines,
    )


def build_news_summary_message(*, ticker: str, result: NewsAggregationResult) -> str:
    return (
        f"### News Research: {ticker}\n\n"
        f"**Overall Sentiment:** {result.sentiment_label.upper()} ({result.weighted_score})\n\n"
        f"**Analysis Summaries:**\n{result.summary_text}\n\n"
        f"**Themes:** {', '.join(result.key_themes) or 'N/A'}"
    )
