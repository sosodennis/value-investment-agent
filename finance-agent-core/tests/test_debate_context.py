from langchain_core.messages import AIMessage

from src.agents.debate.application.debate_context import (
    build_debate_artifact_context,
    build_debate_conversation_context,
)


def test_build_debate_artifact_context_reads_all_ids_and_cache() -> None:
    state = {
        "intent_extraction": {"resolved_ticker": "MSFT"},
        "fundamental_analysis": {"financial_reports_artifact_id": "fa-1"},
        "financial_news_research": {
            "artifact": {"reference": {"artifact_id": "news-1"}}
        },
        "technical_analysis": {"artifact": {"reference": {"artifact_id": "ta-1"}}},
        "compressed_reports": "cached",
    }

    context = build_debate_artifact_context(state)
    assert context.ticker == "MSFT"
    assert context.financial_reports_artifact_id == "fa-1"
    assert context.news_artifact_id == "news-1"
    assert context.technical_artifact_id == "ta-1"
    assert context.cached_reports == "cached"


def test_build_debate_conversation_context_extracts_history_and_debate() -> None:
    state = {
        "intent_extraction": {"resolved_ticker": "TSLA"},
        "history": [AIMessage(content="message", name="Judge")],
        "debate": {"bull_thesis": "x", "bear_thesis": "y"},
    }
    context = build_debate_conversation_context(state)
    assert context.ticker == "TSLA"
    assert len(context.history) == 1
    assert context.debate_context.get("bull_thesis") == "x"
