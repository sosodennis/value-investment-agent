from langchain_core.messages import AIMessage

from src.agents.debate.domain.models import EvidenceFact
from src.agents.debate.interface.mappers import summarize_debate_for_preview
from src.agents.debate.interface.serializers import (
    build_compressed_report_payload,
    build_final_report_payload,
)
from src.shared.kernel.traceable import ManualProvenance


def test_summarize_debate_for_preview_full():
    ctx = {
        "final_verdict": "STRONG_LONG",
        "kelly_confidence": 0.85,
        "winning_thesis": "Growth continues to outperform expectations.",
        "primary_catalyst": "Next earnings call",
        "primary_risk": "Regulatory headwinds",
        "current_round": 3,
    }
    preview = summarize_debate_for_preview(ctx)

    assert preview["verdict_display"] == "📈 STRONG_LONG (85%)"
    assert preview["thesis_display"] == "Growth continues to outperform expectations."
    assert preview["catalyst_display"] == "Next earnings call"
    assert preview["risk_display"] == "Regulatory headwinds"
    assert "Completed 3 rounds" in preview["debate_rounds_display"]


def test_summarize_debate_for_preview_partial():
    ctx = {"final_verdict": "NEUTRAL", "current_round": 1}
    preview = summarize_debate_for_preview(ctx)

    assert "⚖️ NEUTRAL" in preview["verdict_display"]
    assert preview["thesis_display"] == "Analyzing investment thesis..."
    assert "Completed 1 rounds" in preview["debate_rounds_display"]


def test_summarize_debate_for_preview_empty():
    ctx = {}
    preview = summarize_debate_for_preview(ctx)

    assert "⚖️ NEUTRAL" in preview["verdict_display"]
    assert "Analyzing" in preview["thesis_display"]


def test_build_final_report_payload_serializes_facts_and_history():
    payload = build_final_report_payload(
        conclusion_data={
            "scenario_analysis": {
                "bull_case": {
                    "probability": 60.0,
                    "outcome_description": "Upside scenario",
                    "price_implication": "MODERATE_UP",
                },
                "bear_case": {
                    "probability": 20.0,
                    "outcome_description": "Downside scenario",
                    "price_implication": "MODERATE_DOWN",
                },
                "base_case": {
                    "probability": 40.0,
                    "outcome_description": "Base scenario",
                    "price_implication": "FLAT",
                },
            },
            "risk_profile": "GROWTH_TECH",
            "final_verdict": "LONG",
            "winning_thesis": "Core thesis",
            "primary_catalyst": "Catalyst",
            "primary_risk": "Risk",
            "supporting_factors": ["A"],
            "debate_rounds": 3,
        },
        valid_facts=[
            EvidenceFact(
                fact_id="F001",
                source_type="financials",
                source_weight="HIGH",
                summary="Revenue growth",
                value=12.5,
                units="%",
                period="2025",
                provenance=ManualProvenance(description="Manual test fact"),
            )
        ],
        history=[AIMessage(content="Bull argument", name="GrowthHunter")],
    )

    assert payload["final_verdict"] == "LONG"
    assert payload["facts"][0]["fact_id"] == "F001"
    assert payload["history"][0]["content"] == "Bull argument"


def test_build_compressed_report_payload_serializes_sources() -> None:
    class _SourceData:
        financial_reports = [{"base": {"total_revenue": {"value": 100.0}}}]
        news_items = [{"title": "Headline"}]
        technical_payload = {"signal_state": {"direction": "BUY"}}

    payload = build_compressed_report_payload(
        ticker="GME",
        source_data=_SourceData(),
    )

    assert payload["ticker"] == "GME"
    assert payload["financials"]["source_weight"] == "HIGH"
    assert payload["news"]["source_weight"] == "MEDIUM"
    assert payload["technical_analysis"]["source_weight"] == "HIGH"
