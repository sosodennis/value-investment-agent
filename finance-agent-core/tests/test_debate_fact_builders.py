from src.agents.debate.domain.fact_builders import (
    build_financial_facts,
    build_news_facts,
    build_technical_facts,
    render_strict_facts_registry,
    summarize_facts_by_source,
)
from src.common.traceable import ManualProvenance, XBRLProvenance


def test_build_financial_facts_uses_xbrl_provenance_when_available():
    reports = [
        {
            "base": {
                "fiscal_year": {"value": "2024"},
                "total_revenue": {
                    "value": 1000.0,
                    "provenance": {"concept": "us-gaap:Revenues", "period": "FY2024"},
                },
            },
            "extension": {},
            "industry_type": "General",
        }
    ]

    facts = build_financial_facts(reports, start_index=1)

    assert len(facts) == 1
    assert facts[0].fact_id == "F001"
    assert isinstance(facts[0].provenance, XBRLProvenance)


def test_build_news_and_technical_facts_and_summary():
    news_items = [
        {
            "title": "Example title",
            "published_at": "2026-01-01T00:00:00Z",
            "source": {"name": "Reuters"},
            "analysis": {
                "key_facts": [{"content": "Demand improved quarter-over-quarter"}]
            },
        }
    ]
    ta_payload = {"signal_state": {"direction": "BULLISH", "z_score": 2.1}}

    news_facts = build_news_facts(news_items, start_index=1)
    ta_facts = build_technical_facts(ta_payload, ta_artifact_id="ta-123", start_index=2)
    facts = news_facts + ta_facts

    assert len(news_facts) == 1
    assert news_facts[0].fact_id == "N001"
    assert len(ta_facts) == 1
    assert ta_facts[0].fact_id == "T002"
    assert isinstance(ta_facts[0].provenance, ManualProvenance)

    summary = summarize_facts_by_source(facts)
    assert summary == {"financials": 0, "news": 1, "technicals": 1}

    registry = render_strict_facts_registry(facts)
    assert "[N001]" in registry
    assert "[T002]" in registry
