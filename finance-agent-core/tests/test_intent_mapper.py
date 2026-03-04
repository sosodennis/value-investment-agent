import json

from src.agents.intent.domain.models import TickerCandidate
from src.agents.intent.interface.mappers import summarize_intent_for_preview
from src.agents.intent.interface.serializers import (
    serialize_ticker_candidates,
    serialize_ticker_selection_interrupt_payload,
)


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


def test_serialize_ticker_candidates_converts_domain_vo_to_json_payload():
    payload = serialize_ticker_candidates(
        [
            TickerCandidate(symbol="GME", name="GameStop Corp.", confidence=0.98),
            TickerCandidate(
                symbol="GMED", name="Globus Medical, Inc.", confidence=0.73
            ),
        ]
    )

    assert payload[0]["symbol"] == "GME"
    assert payload[0]["name"] == "GameStop Corp."
    assert payload[1]["symbol"] == "GMED"


def test_serialize_ticker_selection_interrupt_payload_serializes_intent_and_candidates():
    payload = serialize_ticker_selection_interrupt_payload(
        candidates=[
            TickerCandidate(symbol="GME", name="GameStop Corp.", confidence=0.98),
        ],
        extracted_intent={
            "company_name": "GameStop",
            "ticker": "GME",
            "is_valuation_request": True,
            "reasoning": "User asked valuation",
        },
    )

    assert payload["type"] == "ticker_selection"
    assert payload["intent"]["ticker"] == "GME"
    assert payload["candidates"][0]["symbol"] == "GME"
