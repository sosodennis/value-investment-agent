import json

from src.agents.news.interface.mappers import summarize_news_for_preview


def test_summarize_news_for_preview_success():
    """Test standard success case with valid metadata and news items."""
    ctx = {
        "status": "success",
        "sentiment_summary": "bullish",
        "sentiment_score": 0.72,
        "article_count": 12,
    }
    news_items = [
        {"title": "Apple hits new all-time high"},
        {"title": "iPhone sales exceed expectations"},
        {"title": "Apple announced new AI features"},
        {"title": "Extra item that should be ignored"},
    ]

    preview = summarize_news_for_preview(ctx, news_items)

    assert preview["status_label"] == "完成"
    assert "📈 bullish (0.72)" in preview["sentiment_display"]
    assert preview["article_count_display"] == "分析了 12 篇新聞"
    assert len(preview["top_headlines"]) == 3
    assert preview["top_headlines"][0] == "Apple hits new all-time high"
    assert preview["top_headlines"][2] == "Apple announced new AI features"


def test_summarize_news_for_preview_negative_sentiment():
    """Test formatting for negative sentiment scores."""
    ctx = {
        "status": "success",
        "sentiment_summary": "bearish",
        "sentiment_score": -0.456,
        "article_count": 5,
    }
    news_items = [{"title": "Revenue decline reported"}]

    preview = summarize_news_for_preview(ctx, news_items)

    assert "📉 bearish (-0.46)" in preview["sentiment_display"]
    assert preview["status_label"] == "完成"


def test_summarize_news_for_preview_neutral():
    """Test formatting for neutral sentiment scores (near zero)."""
    ctx = {
        "status": "success",
        "sentiment_summary": "neutral",
        "sentiment_score": 0.05,
        "article_count": 8,
    }
    news_items = []

    preview = summarize_news_for_preview(ctx, news_items)

    assert "⚖️ neutral (0.05)" in preview["sentiment_display"]


def test_summarize_news_for_preview_empty_news():
    """Test behavior when news_items list is empty."""
    ctx = {
        "status": "success",
        "sentiment_summary": "neutral",
        "sentiment_score": 0.0,
        "article_count": 0,
    }
    news_items = []

    preview = summarize_news_for_preview(ctx, news_items)

    assert preview["top_headlines"] == []
    assert preview["article_count_display"] == "分析了 0 篇新聞"


def test_summarize_news_for_preview_none_score():
    """Test defensive handling of None sentiment score."""
    ctx = {
        "status": "success",
        "sentiment_summary": "neutral",
        "sentiment_score": None,
        "article_count": 0,
    }
    news_items = []

    preview = summarize_news_for_preview(ctx, news_items)

    assert "0.00" in preview["sentiment_display"]
    assert "⚖️" in preview["sentiment_display"]


def test_preview_size_constraint():
    """Verify that the generated preview data is well under the 1KB limit."""
    ctx = {
        "status": "success",
        "sentiment_summary": "bullish",
        "sentiment_score": 0.99,
        "article_count": 100,
    }
    news_items = [
        {"title": "A" * 200},
        {"title": "B" * 200},
        {"title": "C" * 200},
    ]

    preview = summarize_news_for_preview(ctx, news_items)
    serialized = json.dumps(preview)

    # Size in bytes (should be ~700-800 bytes even with long headlines)
    size_bytes = len(serialized.encode("utf-8"))
    assert size_bytes < 1024
    assert size_bytes > 100


def test_summarize_news_for_preview_missing_fields():
    """Test defensive handling of completely missing fields in ctx."""
    ctx = {}
    news_items = []

    preview = summarize_news_for_preview(ctx, news_items)

    # Should have defaults
    assert preview["status_label"] == "處理中"
    assert "neutral" in preview["sentiment_display"]
    assert "0.00" in preview["sentiment_display"]
    assert preview["article_count_display"] == "分析了 0 篇新聞"
    assert preview["top_headlines"] == []


def test_summarize_news_for_preview_headlines_from_context():
    """Test headlines are extracted from context when news_items list is empty/missing."""
    ctx = {
        "status": "success",
        "sentiment_summary": "bullish",
        "sentiment_score": 0.8,
        "article_count": 5,
        "top_headlines": ["Headline 1", "Headline 2", "Headline 3", "Headline 4"],
    }
    # Test with None for news_items
    preview = summarize_news_for_preview(ctx, None)

    assert preview["top_headlines"] == ["Headline 1", "Headline 2", "Headline 3"]
    assert "📈 bullish (0.80)" in preview["sentiment_display"]

    # Test with empty list
    preview_empty = summarize_news_for_preview(ctx, [])
    assert preview_empty["top_headlines"] == ["Headline 1", "Headline 2", "Headline 3"]
