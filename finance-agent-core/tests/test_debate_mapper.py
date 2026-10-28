import re

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from src.agents.debate.domain.entities import DebateVerdictDraft, EvidenceFact
from src.agents.debate.interface.preview_projection_service import (
    summarize_debate_for_preview,
)
from src.agents.debate.interface.prompt_specs import VERDICT_PROMPT
from src.agents.debate.interface.serializers import (
    build_compressed_report_payload,
    build_final_report_payload,
)
from src.agents.fundamental.domain.shared.contracts.traceable import ManualProvenance
from src.shared.artifacts.debate_contracts import DebateHistoryMessageModel


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


def test_summarize_debate_preview_uses_deterministic_conviction_when_available():
    preview = summarize_debate_for_preview(
        {"final_verdict": "LONG", "conviction": 70, "current_round": 3}
    )

    assert preview["verdict_display"] == "📈 LONG (70%)"


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
            ),
            EvidenceFact(
                fact_id="V001",
                source_type="valuation",
                source_weight="MEDIUM",
                summary="Intrinsic value estimate",
                value=124.58,
                units="USD/share",
                provenance=ManualProvenance(description="Valuation test fact"),
            ),
        ],
        history=[
            AIMessage(
                content="Bull argument",
                name="GrowthHunter",
                additional_kwargs={"round_num": 2},
            ),
            AIMessage(
                content="Moderator review",
                name="Judge",
                additional_kwargs={"round_num": 2},
            ),
            AIMessage(content="Legacy argument", name="ForensicAccountant"),
        ],
    )

    assert payload["final_verdict"] == "LONG"
    assert payload["facts"][0]["fact_id"] == "F001"
    assert payload["facts"][1]["fact_id"] == "V001"
    assert payload["history"][0]["content"] == "Bull argument"
    assert payload["history"][0]["round_num"] == 2
    assert payload["history"][1]["round_num"] == 2
    assert "round_num" not in payload["history"][2]


def test_verdict_draft_uses_fixed_scenarios_and_builds_artifact_contract() -> None:
    draft = DebateVerdictDraft.model_validate(
        {
            "scenario_analysis": {
                "bull_case": {
                    "probability": 47.5,
                    "outcome_description": "Services growth remains durable.",
                    "price_implication": "MODERATE_UP",
                },
                "bear_case": {
                    "probability": 22,
                    "outcome_description": "Margins contract under competition.",
                    "price_implication": "MODERATE_DOWN",
                },
                "base_case": {
                    "probability": 50,
                    "outcome_description": "The current valuation holds.",
                    "price_implication": "FLAT",
                },
            },
            "risk_profile": "GROWTH_TECH",
            "winning_thesis": "Installed base supports continued services growth.",
            "primary_catalyst": "Services revenue growth.",
            "primary_risk": "Hardware replacement demand weakens.",
            "supporting_factors": ["Recurring customer relationships."],
        }
    )

    payload = build_final_report_payload(
        conclusion_data={
            **draft.model_dump(mode="json"),
            "final_verdict": "LONG",
            "conviction": 70,
            "rr_ratio": 1.5,
            "alpha": 0.03,
            "risk_free_benchmark": 0.04,
            "raw_ev": 0.07,
            "analysis_bias": "BULLISH",
            "model_summary": "Reward/Risk: 1.50x, Alpha: 3.00%",
            "data_quality_warning": False,
            "debate_rounds": 3,
        },
        valid_facts=[],
        history=[],
    )

    assert payload["scenario_analysis"]["bull_case"]["probability"] == 47.5
    assert payload["conviction"] == 70
    scenario_schema = DebateVerdictDraft.model_json_schema()["$defs"][
        "ScenarioAnalysis"
    ]
    assert scenario_schema["additionalProperties"] is False
    assert scenario_schema["required"] == ["bull_case", "bear_case", "base_case"]


def test_verdict_prompt_example_matches_the_structured_output_contract() -> None:
    prompt = VERDICT_PROMPT.format(ticker="AAPL", history="Example debate history.")
    match = re.search(r"```json\s*(\{.*?\})\s*```", prompt, re.DOTALL)

    assert match is not None
    draft = DebateVerdictDraft.model_validate_json(match.group(1))
    assert draft.scenario_analysis.bull_case.price_implication == "MODERATE_UP"


def test_verdict_draft_rejects_missing_scenario_and_calculated_fields() -> None:
    with pytest.raises(ValidationError):
        DebateVerdictDraft.model_validate(
            {
                "scenario_analysis": {"bull_case": {}},
                "risk_profile": "GROWTH_TECH",
                "winning_thesis": "Thesis",
                "primary_catalyst": "Catalyst",
                "primary_risk": "Risk",
                "supporting_factors": [],
                "final_verdict": "LONG",
            }
        )


@pytest.mark.parametrize("probability", [-1, 100.1])
def test_verdict_draft_rejects_probability_outside_score_range(
    probability: float,
) -> None:
    with pytest.raises(ValidationError):
        DebateVerdictDraft.model_validate(
            {
                "scenario_analysis": {
                    "bull_case": {
                        "probability": probability,
                        "outcome_description": "Bull case",
                        "price_implication": "MODERATE_UP",
                    },
                    "bear_case": {
                        "probability": 20,
                        "outcome_description": "Bear case",
                        "price_implication": "MODERATE_DOWN",
                    },
                    "base_case": {
                        "probability": 30,
                        "outcome_description": "Base case",
                        "price_implication": "FLAT",
                    },
                },
                "risk_profile": "GROWTH_TECH",
                "winning_thesis": "Thesis",
                "primary_catalyst": "Catalyst",
                "primary_risk": "Risk",
                "supporting_factors": [],
            }
        )


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


@pytest.mark.parametrize("round_num", [0, 1.5, True])
def test_debate_history_contract_rejects_invalid_round_num(round_num):
    with pytest.raises(TypeError, match="positive integer"):
        DebateHistoryMessageModel(content="Invalid round", round_num=round_num)
