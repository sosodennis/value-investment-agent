from src.agents.debate.domain.fact_builders import (
    build_financial_facts,
    build_news_facts,
    build_technical_facts,
    build_valuation_facts,
    render_strict_facts_registry,
    summarize_facts_by_source,
)
from src.agents.fundamental.shared.contracts.traceable import (
    ManualProvenance,
    XBRLProvenance,
)


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
    assert len(ta_facts) >= 1
    assert ta_facts[0].fact_id == "T002"
    assert isinstance(ta_facts[0].provenance, ManualProvenance)

    summary = summarize_facts_by_source(facts)
    assert summary == {
        "financials": 0,
        "news": 1,
        "technicals": len(ta_facts),
        "valuation": 0,
    }

    registry = render_strict_facts_registry(facts)
    assert "[N001]" in registry
    assert "[T002]" in registry


def test_build_valuation_facts_from_preview():
    preview = {
        "model_type": "dcf_growth",
        "intrinsic_value": 124.58,
        "upside_potential": 0.205,
        "distribution_scenarios": {
            "bear": {"label": "P5 (Bear)", "price": 92.62},
            "base": {"label": "P50 (Base)", "price": 124.58},
            "bull": {"label": "P95 (Bull)", "price": 228.91},
        },
    }
    facts = build_valuation_facts(preview, start_index=1)

    assert len(facts) == 6
    assert facts[0].fact_id == "V001"
    assert facts[0].source_type == "valuation"
    assert facts[1].summary.startswith("Intrinsic value estimate")
    assert facts[2].summary.startswith("Upside potential")
    assert facts[-1].summary.startswith("Valuation distribution P95")

    summary = summarize_facts_by_source(facts)
    assert summary == {"financials": 0, "news": 0, "technicals": 0, "valuation": 6}


def test_build_technical_facts_expands_signal_and_confluence_metrics():
    ta_payload = {
        "frac_diff_metrics": {"optimal_d": 0.43, "memory_strength": "balanced"},
        "signal_state": {
            "direction": "bullish",
            "z_score": 1.8,
            "confluence": {
                "bollinger_state": "upper_band",
                "macd_momentum": "uptrend",
                "obv_state": "accumulation",
            },
        },
    }
    facts = build_technical_facts(ta_payload, ta_artifact_id="ta-xyz", start_index=10)

    assert len(facts) == 6
    assert [fact.fact_id for fact in facts] == [
        "T010",
        "T011",
        "T012",
        "T013",
        "T014",
        "T015",
    ]
    assert facts[0].summary.startswith("Technical signal direction")
    assert facts[-1].summary.startswith("OBV state")
