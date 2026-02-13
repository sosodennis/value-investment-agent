import json

from src.agents.intent.interface.mappers import summarize_intent_for_preview


def test_summarize_intent_with_resolved_ticker():
    ctx = {
        "resolved_ticker": "AAPL",
        "company_profile": {"name": "Apple Inc.", "exchange": "NASDAQ"},
        "status": "resolved",
    }
    preview = summarize_intent_for_preview(ctx)

    assert preview["ticker"] == "AAPL"
    assert preview["company_name"] == "Apple Inc."
    assert preview["status_label"] == "已確認標的"
    assert preview["exchange"] == "NASDAQ"
    # Ensure it's JSON serializable and small
    serialized = json.dumps(preview)
    assert len(serialized) < 1024


def test_summarize_intent_searching():
    ctx = {"status": "searching", "extracted_intent": {"company_name": "Apple"}}
    preview = summarize_intent_for_preview(ctx)

    assert preview["ticker"] is None
    assert preview["status_label"] == "搜尋股票代號中..."
    assert preview["company_name"] is None


def test_summarize_intent_empty():
    preview = summarize_intent_for_preview({})
    assert preview["status_label"] == "準備中"
    assert preview["ticker"] is None
    assert preview["company_name"] is None


def test_summarize_intent_clarifying():
    ctx = {"status": "clarifying"}
    preview = summarize_intent_for_preview(ctx)
    assert preview["status_label"] == "等待訊息輸入..."
