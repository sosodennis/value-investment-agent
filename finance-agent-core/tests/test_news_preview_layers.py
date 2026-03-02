from src.agents.news.interface.formatters import format_news_preview
from src.agents.news.interface.preview_projection_service import (
    derive_news_preview_view_model,
)


def test_derive_news_preview_view_model_extracts_canonical_fields() -> None:
    vm = derive_news_preview_view_model(
        {
            "status": "success",
            "sentiment_summary": "bullish",
            "sentiment_score": 0.72,
            "article_count": 12,
        },
        [
            {"title": "T1"},
            {"title": "T2"},
            {"title": "T3"},
            {"title": "T4"},
        ],
    )
    assert vm["status"] == "success"
    assert vm["sentiment_summary"] == "bullish"
    assert vm["sentiment_score"] == 0.72
    assert vm["article_count"] == 12
    assert vm["top_headlines"] == ["T1", "T2", "T3"]


def test_format_news_preview_applies_display_formatting() -> None:
    preview = format_news_preview(
        {
            "status": "success",
            "sentiment_summary": "bearish",
            "sentiment_score": -0.45,
            "article_count": 5,
            "top_headlines": ["H1", "H2"],
        }
    )
    assert preview["status_label"] == "完成"
    assert "📉 bearish (-0.45)" in preview["sentiment_display"]
    assert preview["article_count_display"] == "分析了 5 篇新聞"
    assert preview["top_headlines"] == ["H1", "H2"]
