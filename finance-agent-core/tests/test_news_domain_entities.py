from __future__ import annotations

from src.agents.news.data.mappers import to_news_item_entities
from src.agents.news.domain.services import aggregate_news_items


def test_to_news_item_entities_projects_expected_fields() -> None:
    entities = to_news_item_entities(
        [
            {
                "title": "A",
                "source": {"reliability_score": 0.9},
                "analysis": {
                    "sentiment_score": 0.5,
                    "summary": "good",
                    "key_event": "earnings",
                    "key_facts": [{"content": "eps up"}],
                },
            },
            {"title": "B"},
        ]
    )

    assert len(entities) == 2
    assert entities[0].title == "A"
    assert entities[0].source is not None
    assert entities[0].source.reliability_score == 0.9
    assert entities[0].analysis is not None
    assert entities[0].analysis.key_facts_count == 1
    assert entities[1].analysis is None


def test_aggregate_news_items_uses_entity_projection() -> None:
    entities = to_news_item_entities(
        [
            {
                "title": "A",
                "source": {"reliability_score": 1.0},
                "analysis": {
                    "sentiment_score": 0.8,
                    "summary": "positive",
                    "key_event": "beat",
                    "key_facts": [],
                },
            },
            {
                "title": "B",
                "source": {"reliability_score": 1.0},
                "analysis": {
                    "sentiment_score": -0.3,
                    "summary": "risk",
                    "key_event": "risk",
                    "key_facts": [],
                },
            },
        ]
    )

    result = aggregate_news_items(entities, ticker="GME")
    assert result.sentiment_label == "neutral"
    assert result.top_headlines == ["A", "B"]
