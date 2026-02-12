from __future__ import annotations

import pytest

from src.interface.canonical_serializers import (
    canonicalize_debate_artifact_data,
    canonicalize_fundamental_artifact_data,
    canonicalize_news_artifact_data,
    canonicalize_technical_artifact_data,
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
                "industry_type": "Financial",
                "base": {
                    "fiscal_year": {"value": "2024"},
                    "fiscal_period": {"value": "FY"},
                    "period_end_date": "2024-09-28",
                    "currency": "USD",
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
                "extension": {"loans_and_leases": 1.0},
            }
        ],
    }

    normalized = canonicalize_fundamental_artifact_data(payload)

    assert normalized["company_name"] == "AAPL"
    assert normalized["sector"] == "Unknown"
    assert normalized["industry"] == "Unknown"
    assert normalized["reasoning"] == ""

    report = normalized["financial_reports"][0]
    assert report["extension_type"] == "FinancialServices"
    assert report["base"]["period_end_date"] == {"value": "2024-09-28"}
    assert report["base"]["currency"] == {"value": "USD"}


def test_canonicalize_technical_artifact_normalizes_enums_and_series() -> None:
    payload = {
        "ticker": "TSLA",
        "timestamp": "2026-02-12T12:00:00",
        "frac_diff_metrics": {
            "optimal_d": 0.44,
            "window_length": 252,
            "adf_statistic": -3.7,
            "adf_pvalue": 0.01,
            "memory_strength": "BALANCED",
        },
        "signal_state": {
            "z_score": 2.3,
            "statistical_state": "STATISTICAL_ANOMALY",
            "direction": "BULLISH_EXTENSION",
            "risk_level": "high",
            "confluence": {
                "bollinger_state": "BREAKOUT_UPPER",
                "macd_momentum": "BULLISH_EXPANDING",
                "obv_state": "ACCUMULATING",
                "statistical_strength": 97.0,
            },
        },
        "semantic_tags": ["STATISTICAL_EXTREME"],
        "raw_data": {
            "price_series": {
                "2026-01-01": 100.0,
                "2026-01-02": None,
            },
            "z_score_series": {
                "2026-01-01": 1.5,
                "2026-01-02": float("nan"),
            },
        },
    }

    normalized = canonicalize_technical_artifact_data(payload)

    assert normalized["frac_diff_metrics"]["memory_strength"] == "balanced"
    assert normalized["signal_state"]["statistical_state"] == "anomaly"
    assert normalized["signal_state"]["risk_level"] == "critical"
    assert normalized["raw_data"]["price_series"] == {"2026-01-01": 100.0}
    assert normalized["raw_data"]["z_score_series"] == {"2026-01-01": 1.5}


def test_canonicalize_technical_artifact_rejects_invalid_risk_level() -> None:
    payload = {
        "ticker": "TSLA",
        "timestamp": "2026-02-12T12:00:00",
        "frac_diff_metrics": {
            "optimal_d": 0.44,
            "window_length": 252,
            "adf_statistic": -3.7,
            "adf_pvalue": 0.01,
            "memory_strength": "balanced",
        },
        "signal_state": {
            "z_score": 0.1,
            "statistical_state": "equilibrium",
            "direction": "NEUTRAL_CONSOLIDATION",
            "risk_level": "severe",
            "confluence": {
                "bollinger_state": "INSIDE",
                "macd_momentum": "NEUTRAL",
                "obv_state": "NEUTRAL",
                "statistical_strength": 50.0,
            },
        },
        "semantic_tags": [],
    }

    with pytest.raises(TypeError, match="risk_level"):
        canonicalize_technical_artifact_data(payload)


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

    normalized = canonicalize_news_artifact_data(payload)
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

    normalized = canonicalize_debate_artifact_data(payload)
    assert normalized["risk_profile"] == "GROWTH_TECH"
    assert normalized["final_verdict"] == "LONG"
    assert normalized["scenario_analysis"]["bull_case"]["price_implication"] == "SURGE"
    assert normalized["facts"][0]["source_type"] == "news"
    assert normalized["facts"][0]["source_weight"] == "HIGH"
    assert "analysis_bias" not in normalized
