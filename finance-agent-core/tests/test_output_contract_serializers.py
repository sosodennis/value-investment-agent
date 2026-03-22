from __future__ import annotations

import pytest

from src.agents.debate.interface.contracts import parse_debate_artifact_model
from src.agents.fundamental.subdomains.artifacts_provenance.interface.contracts import (
    parse_fundamental_artifact_model,
)
from src.agents.news.interface.contracts import parse_news_artifact_model
from src.agents.technical.interface.contracts import (
    parse_technical_artifact_model,
)


def test_canonicalize_fundamental_artifact_normalizes_reports() -> None:
    payload = {
        "ticker": "AAPL",
        "model_type": "saas",
        "company_name": None,
        "sector": None,
        "industry": None,
        "reasoning": None,
        "status": "done",
        "financial_reports": [
            {
                "industry_type": "FinancialServices",
                "extension_type": "FinancialServices",
                "base": {
                    "fiscal_year": {"value": "2024"},
                    "fiscal_period": {"value": "FY"},
                    "period_end_date": {"value": "2024-09-28"},
                    "currency": {"value": "USD"},
                    "company_name": {"value": "Apple Inc."},
                    "cik": {"value": "0000320193"},
                    "sic_code": {"value": "3571"},
                    "shares_outstanding": {"value": 15500000000},
                    "total_revenue": {"value": 391000000000},
                    "net_income": {"value": 93700000000},
                    "income_tax_expense": {"value": 16000000000},
                    "total_assets": {"value": 352000000000},
                    "total_liabilities": {"value": 290000000000},
                    "total_equity": {"value": 62000000000},
                    "cash_and_equivalents": {"value": 30000000000},
                    "operating_cash_flow": {"value": 110000000000},
                },
                "extension": {"loans_and_leases": {"value": 1.0}},
            }
        ],
        "valuation_diagnostics": {
            "forward_signal_mapping_version": "forward_signal_calibration_v2_2026_03_05",
            "forward_signal_calibration_applied": True,
        },
    }

    normalized = parse_fundamental_artifact_model(payload)

    assert normalized["company_name"] == "AAPL"
    assert normalized["sector"] == "Unknown"
    assert normalized["industry"] == "Unknown"
    assert normalized["reasoning"] == ""

    report = normalized["financial_reports"][0]
    assert report["industry_type"] == "FinancialServices"
    assert report["extension_type"] == "FinancialServices"
    assert report["base"]["period_end_date"] == {"value": "2024-09-28"}
    assert report["base"]["currency"] == {"value": "USD"}
    assert (
        normalized["valuation_diagnostics"]["forward_signal_mapping_version"]
        == "forward_signal_calibration_v2_2026_03_05"
    )
    assert (
        normalized["valuation_diagnostics"]["forward_signal_calibration_applied"]
        is True
    )


def test_canonicalize_technical_artifact_normalizes_enums_and_series() -> None:
    payload = {
        "schema_version": "2.0",
        "ticker": "TSLA",
        "as_of": "2026-02-12T12:00:00",
        "direction": "BULLISH_EXTENSION",
        "risk_level": "high",
        "confidence": 0.63,
        "summary_tags": ["STATISTICAL_EXTREME"],
        "diagnostics": {"is_degraded": False, "degraded_reasons": []},
        "artifact_refs": {
            "chart_data_id": "chart-1",
            "timeseries_bundle_id": "bundle-1",
            "feature_pack_id": "feature-1",
        },
    }

    normalized = parse_technical_artifact_model(payload)

    assert normalized["risk_level"] == "critical"


def test_canonicalize_technical_artifact_rejects_invalid_risk_level() -> None:
    payload = {
        "schema_version": "2.0",
        "ticker": "TSLA",
        "as_of": "2026-02-12T12:00:00",
        "direction": "NEUTRAL_CONSOLIDATION",
        "risk_level": "severe",
        "confidence": 0.2,
        "summary_tags": [],
        "diagnostics": {"is_degraded": False, "degraded_reasons": []},
        "artifact_refs": {
            "chart_data_id": "chart-1",
            "timeseries_bundle_id": "bundle-1",
            "feature_pack_id": "feature-1",
        },
    }

    with pytest.raises(TypeError, match="risk_level"):
        parse_technical_artifact_model(payload)


def test_canonicalize_news_artifact_normalizes_enums() -> None:
    payload = {
        "ticker": "NVDA",
        "news_items": [
            {
                "id": "n1",
                "url": "https://example.com/news",
                "published_at": None,
                "fetched_at": "2026-02-12T12:00:00Z",
                "title": "Test",
                "snippet": "Snippet",
                "source": {
                    "name": "Reuters",
                    "domain": "reuters.com",
                    "reliability_score": 0.9,
                    "author": None,
                },
                "related_tickers": [
                    {
                        "ticker": "NVDA",
                        "company_name": "NVIDIA",
                        "relevance_score": 0.98,
                    }
                ],
                "categories": ["TRUSTED_NEWS", "BULLISH"],
                "tags": ["earnings"],
                "analysis": {
                    "summary": "Positive demand outlook",
                    "sentiment": "BULLISH",
                    "sentiment_score": 0.7,
                    "impact_level": "HIGH",
                    "key_event": None,
                    "reasoning": "Guidance beat",
                    "key_facts": [
                        {
                            "content": "Data center revenue grew",
                            "is_quantitative": True,
                            "sentiment": "bullish",
                            "citation": None,
                        }
                    ],
                },
            }
        ],
        "overall_sentiment": "BULLISH",
        "sentiment_score": 0.7,
        "key_themes": ["AI demand"],
    }

    normalized = parse_news_artifact_model(payload)
    item = normalized["news_items"][0]
    assert normalized["overall_sentiment"] == "bullish"
    assert item["categories"] == ["trusted_news", "bullish"]
    assert item["analysis"]["impact_level"] == "high"
    assert item["analysis"]["sentiment"] == "bullish"


def test_canonicalize_debate_artifact_normalizes_and_filters_optional() -> None:
    payload = {
        "scenario_analysis": {
            "bull_case": {
                "probability": 60,
                "outcome_description": "Upside",
                "price_implication": "surge",
            },
            "bear_case": {
                "probability": 20,
                "outcome_description": "Downside",
                "price_implication": "CRASH",
            },
            "base_case": {
                "probability": 20,
                "outcome_description": "Flat",
                "price_implication": "FLAT",
            },
        },
        "risk_profile": "growth_tech",
        "final_verdict": "long",
        "winning_thesis": "Momentum + fundamentals",
        "primary_catalyst": "AI capex cycle",
        "primary_risk": "Valuation compression",
        "supporting_factors": ["Revenue acceleration"],
        "debate_rounds": 3,
        "analysis_bias": None,
        "history": [{"name": None, "role": "assistant", "content": "argument"}],
        "facts": [
            {
                "fact_id": "F001",
                "source_type": "NEWS",
                "source_weight": "high",
                "summary": "EPS beat",
                "value": 3.2,
                "units": None,
                "period": "Q4",
                "provenance": {"type": "MANUAL", "description": "test"},
            }
        ],
    }

    normalized = parse_debate_artifact_model(payload)
    assert normalized["risk_profile"] == "GROWTH_TECH"
    assert normalized["final_verdict"] == "LONG"
    assert normalized["scenario_analysis"]["bull_case"]["price_implication"] == "SURGE"
    assert normalized["facts"][0]["source_type"] == "news"
    assert normalized["facts"][0]["source_weight"] == "HIGH"
    assert "analysis_bias" not in normalized
