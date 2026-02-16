from src.interface.artifacts.artifact_contract_registry import (
    parse_artifact_data_json,
    parse_artifact_data_model_as,
)
from src.interface.artifacts.artifact_data_models import PriceSeriesArtifactData
from src.shared.kernel.contracts import (
    ARTIFACT_KIND_DEBATE_FINAL_REPORT,
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_PRICE_SERIES,
    ARTIFACT_KIND_TA_FULL_REPORT,
)


def _news_item_minimal() -> dict[str, object]:
    return {
        "id": "n1",
        "url": "https://example.com/n1",
        "fetched_at": "2026-02-13T00:00:00+00:00",
        "title": "n1",
        "snippet": "snippet",
        "source": {
            "name": "Reuters",
            "domain": "reuters.com",
            "reliability_score": 0.9,
        },
        "related_tickers": [],
        "categories": ["general"],
        "tags": [],
    }


def test_parse_artifact_data_model_as_routes_kind_to_model() -> None:
    parsed = parse_artifact_data_model_as(
        ARTIFACT_KIND_PRICE_SERIES,
        {
            "price_series": {"2026-01-01": 100.0},
            "volume_series": {"2026-01-01": 1000.0},
        },
        model=PriceSeriesArtifactData,
        context="unit-test",
    )
    assert isinstance(parsed, PriceSeriesArtifactData)
    assert parsed.price_series["2026-01-01"] == 100.0


def test_canonicalize_financial_reports_uses_model_validation_only() -> None:
    canonical = parse_artifact_data_json(
        ARTIFACT_KIND_FINANCIAL_REPORTS,
        {
            "ticker": "AAPL",
            "model_type": "saas",
            "company_name": None,
            "sector": None,
            "industry": None,
            "reasoning": None,
            "status": "done",
            "financial_reports": [
                {
                    "industry_type": "General",
                    "base": {
                        "fiscal_year": {"value": "2024"},
                        "fiscal_period": {"value": "FY"},
                    },
                }
            ],
        },
        context="unit-test",
    )
    assert canonical["ticker"] == "AAPL"
    assert canonical["company_name"] is None
    assert canonical["sector"] is None


def test_canonicalize_debate_uses_domain_normalization() -> None:
    canonical = parse_artifact_data_json(
        ARTIFACT_KIND_DEBATE_FINAL_REPORT,
        {
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
        },
        context="unit-test",
    )
    assert canonical["risk_profile"] == "GROWTH_TECH"
    assert canonical["final_verdict"] == "LONG"
    assert "analysis_bias" not in canonical


def test_parse_artifact_data_json_rejects_unsupported_kind() -> None:
    try:
        parse_artifact_data_json(
            "unsupported_kind",
            {"a": 1},
            context="unit-test",
        )
        raise AssertionError("expected TypeError")
    except TypeError as exc:
        assert "unsupported artifact kind" in str(exc)


def test_parse_artifact_data_json_for_news_report() -> None:
    parsed = parse_artifact_data_json(
        ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
        {
            "ticker": "AAPL",
            "overall_sentiment": "bullish",
            "sentiment_score": 0.8,
            "key_themes": [],
            "news_items": [_news_item_minimal()],
        },
        context="unit-test",
    )
    news_items = parsed.get("news_items")
    assert isinstance(news_items, list)
    assert len(news_items) == 1


def test_parse_artifact_data_json_for_technical_report() -> None:
    parsed = parse_artifact_data_json(
        ARTIFACT_KIND_TA_FULL_REPORT,
        {
            "ticker": "AAPL",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "frac_diff_metrics": {
                "optimal_d": 0.4,
                "window_length": 120,
                "adf_statistic": -3.1,
                "adf_pvalue": 0.03,
                "memory_strength": "balanced",
            },
            "signal_state": {
                "z_score": 1.2,
                "statistical_state": "deviating",
                "direction": "bullish",
                "risk_level": "medium",
                "confluence": {
                    "bollinger_state": "upper_band_touch",
                    "macd_momentum": "positive",
                    "obv_state": "accumulation",
                    "statistical_strength": 0.7,
                },
            },
            "semantic_tags": ["mean-reversion"],
        },
        context="unit-test",
    )
    assert parsed["ticker"] == "AAPL"
