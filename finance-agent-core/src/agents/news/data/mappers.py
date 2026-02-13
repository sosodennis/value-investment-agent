from __future__ import annotations

from src.agents.news.domain.entities import AnalysisEntity, NewsItemEntity, SourceEntity


def _parse_source_entity(value: object) -> SourceEntity | None:
    if not isinstance(value, dict):
        return None
    raw_score = value.get("reliability_score", 0.5)
    if isinstance(raw_score, int | float):
        return SourceEntity(reliability_score=float(raw_score))
    return SourceEntity(reliability_score=0.5)


def _parse_analysis_entity(value: object) -> AnalysisEntity | None:
    if not isinstance(value, dict):
        return None

    raw_score = value.get("sentiment_score", 0.0)
    sentiment_score = float(raw_score) if isinstance(raw_score, int | float) else 0.0

    summary_raw = value.get("summary")
    summary = (
        summary_raw if isinstance(summary_raw, str) and summary_raw else "No summary"
    )

    key_event_raw = value.get("key_event")
    key_event = (
        key_event_raw if isinstance(key_event_raw, str) and key_event_raw else None
    )

    key_facts_raw = value.get("key_facts")
    key_facts_count = len(key_facts_raw) if isinstance(key_facts_raw, list) else 0

    return AnalysisEntity(
        sentiment_score=sentiment_score,
        summary=summary,
        key_event=key_event,
        key_facts_count=key_facts_count,
    )


def to_news_item_entity(value: object) -> NewsItemEntity | None:
    if not isinstance(value, dict):
        return None

    title_raw = value.get("title")
    title = title_raw if isinstance(title_raw, str) and title_raw else None

    return NewsItemEntity(
        title=title,
        source=_parse_source_entity(value.get("source")),
        analysis=_parse_analysis_entity(value.get("analysis")),
    )


def to_news_item_entities(values: list[dict[str, object]]) -> list[NewsItemEntity]:
    result: list[NewsItemEntity] = []
    for value in values:
        entity = to_news_item_entity(value)
        if entity is not None:
            result.append(entity)
    return result
