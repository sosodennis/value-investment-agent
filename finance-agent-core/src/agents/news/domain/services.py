from __future__ import annotations

from src.agents.news.domain.models import NewsAggregationResult
from src.common.types import JSONObject


def aggregate_news_items(
    news_items: list[JSONObject], *, ticker: str
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
            analysis_raw = item.get("analysis")
            if not isinstance(analysis_raw, dict):
                continue
            source_raw = item.get("source")
            source_info = source_raw if isinstance(source_raw, dict) else {}
            weight = float(source_info.get("reliability_score", 0.5))
            total_weight += weight
            weighted_score_sum += (
                float(analysis_raw.get("sentiment_score", 0.0)) * weight
            )

            key_theme_raw = analysis_raw.get("key_event")
            if isinstance(key_theme_raw, str) and key_theme_raw:
                themes.add(key_theme_raw)

            key_facts = analysis_raw.get("key_facts", [])
            facts_count = len(key_facts) if isinstance(key_facts, list) else 0
            summaries.append(
                f"- {analysis_raw.get('summary', 'No summary')} ({facts_count} key facts)"
            )

        weighted_score = weighted_score_sum / total_weight if total_weight > 0 else 0.0
        if weighted_score > 0.3:
            sentiment_label = "bullish"
        elif weighted_score < -0.3:
            sentiment_label = "bearish"

        summary_text = "\n".join(summaries)
        key_themes = list(themes)

    report_payload: JSONObject = {
        "ticker": ticker,
        "news_items": news_items,
        "overall_sentiment": sentiment_label,
        "sentiment_score": round(weighted_score, 2),
        "key_themes": key_themes,
    }
    top_headlines = [
        str(item.get("title"))
        for item in news_items[:3]
        if isinstance(item.get("title"), str) and item.get("title")
    ]
    return NewsAggregationResult(
        sentiment_label=sentiment_label,
        weighted_score=round(weighted_score, 2),
        key_themes=key_themes,
        summary_text=summary_text,
        report_payload=report_payload,
        top_headlines=top_headlines,
    )


def build_news_summary_message(*, ticker: str, result: NewsAggregationResult) -> str:
    return (
        f"### News Research: {ticker}\n\n"
        f"**Overall Sentiment:** {result.sentiment_label.upper()} ({result.weighted_score})\n\n"
        f"**Analysis Summaries:**\n{result.summary_text}\n\n"
        f"**Themes:** {', '.join(result.key_themes) or 'N/A'}"
    )


def build_articles_to_fetch(
    raw_results: list[JSONObject], selected_indices: list[int]
) -> list[JSONObject]:
    selected: list[JSONObject] = []
    for idx in selected_indices:
        if idx >= len(raw_results):
            continue
        selected.append(raw_results[idx])
    return selected


def build_selector_fallback_indices(raw_results: list[JSONObject]) -> list[int]:
    return list(range(min(3, len(raw_results))))


def normalize_selected_indices(
    selected_indices: list[int], *, limit: int = 10
) -> list[int]:
    return list(dict.fromkeys(selected_indices))[:limit]
