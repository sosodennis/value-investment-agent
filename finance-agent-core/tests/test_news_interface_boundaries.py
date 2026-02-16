from __future__ import annotations

import pytest

from src.agents.news.interface.parsers import parse_news_items
from src.agents.news.interface.serializers import build_search_progress_preview


def test_parse_news_items_validates_payload() -> None:
    parsed = parse_news_items(
        [
            {
                "id": "n1",
                "url": "https://example.com/a",
                "title": "Title",
                "snippet": "Snippet",
                "source": {
                    "name": "Reuters",
                    "domain": "example.com",
                    "reliability_score": 0.9,
                },
                "categories": ["general"],
            }
        ],
        context="news items",
    )
    assert len(parsed) == 1
    assert parsed[0].id == "n1"


def test_parse_news_items_rejects_invalid_payload() -> None:
    with pytest.raises(TypeError):
        parse_news_items([{"title": "missing required fields"}], context="news items")


def test_build_search_progress_preview_top_headlines() -> None:
    preview = build_search_progress_preview(
        article_count=4,
        cleaned_results=[
            {"title": "H1"},
            {"title": "H2"},
            {"title": "H3"},
            {"title": "H4"},
        ],
    )
    assert preview["article_count_display"] == "找到 4 篇新聞"
    assert preview["top_headlines"] == ["H1", "H2", "H3"]
