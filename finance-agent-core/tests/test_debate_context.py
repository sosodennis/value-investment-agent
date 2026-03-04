from langchain_core.messages import AIMessage

from src.agents.debate.application.debate_context import (
    build_debate_artifact_context,
    build_debate_conversation_context,
)


def test_build_debate_artifact_context_reads_all_ids_and_cache() -> None:
    state = {
        "intent_extraction": {"resolved_ticker": "MSFT"},
        "fundamental_analysis": {
            "financial_reports_artifact_id": "fa-1",
            "artifact": {"preview": {"intrinsic_value": 123.4}},
        },
        "financial_news_research": {
            "artifact": {"reference": {"artifact_id": "news-1"}}
        },
        "technical_analysis": {"artifact": {"reference": {"artifact_id": "ta-1"}}},
        "context_summary_text": "cached_summary",
        "facts_registry_text": "cached_facts",
    }

    context = build_debate_artifact_context(state)
    assert context.ticker == "MSFT"
    assert context.financial_reports_artifact_id == "fa-1"
    assert context.news_artifact_id == "news-1"
    assert context.technical_artifact_id == "ta-1"
    assert context.fundamental_valuation_preview == {"intrinsic_value": 123.4}
    assert context.cached_context_summary_text == "cached_summary"
    assert context.cached_facts_registry_text == "cached_facts"


def test_build_debate_conversation_context_extracts_history_and_debate() -> None:
    state = {
        "intent_extraction": {"resolved_ticker": "TSLA"},
        "history": [AIMessage(content="message", name="Judge")],
        "bull_thesis": " bull ",
        "bear_thesis": "bear",
        "debate": {"bull_thesis": "x", "bear_thesis": "y"},
    }
    context = build_debate_conversation_context(state)
    assert context.ticker == "TSLA"
    assert len(context.history) == 1
    assert context.debate_context.get("bull_thesis") == "x"
    assert context.bull_thesis == "bull"
    assert context.bear_thesis == "bear"
