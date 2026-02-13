from src.common.contracts import (
    ARTIFACT_KIND_DEBATE_FINAL_REPORT,
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
    ARTIFACT_KIND_NEWS_ITEMS_LIST,
    ARTIFACT_KIND_PRICE_SERIES,
    ARTIFACT_KIND_SEARCH_RESULTS,
)
from src.interface.artifact_api_models import PriceSeriesArtifactData
from src.interface.artifact_contract_registry import (
    canonicalize_artifact_data_by_kind,
    parse_artifact_data_model_as,
    parse_news_items_for_debate,
    parse_technical_debate_payload,
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


def test_canonicalize_financial_reports_detects_full_payload() -> None:
    canonical = canonicalize_artifact_data_by_kind(
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
    assert canonical["company_name"] == "AAPL"
    assert canonical["sector"] == "Unknown"
    assert canonical["industry"] == "Unknown"


def test_canonicalize_debate_uses_domain_normalization() -> None:
    canonical = canonicalize_artifact_data_by_kind(
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


def test_parse_technical_debate_payload_rejects_unsupported_kind() -> None:
    try:
        parse_technical_debate_payload(
            ARTIFACT_KIND_SEARCH_RESULTS,
            {"raw_results": [], "formatted_results": ""},
            context="unit-test",
        )
        raise AssertionError("expected TypeError")
    except TypeError as exc:
        assert "not supported for technical debate payload" in str(exc)


def test_parse_news_items_for_debate_accepts_two_supported_kinds() -> None:
    from_items_list = parse_news_items_for_debate(
        ARTIFACT_KIND_NEWS_ITEMS_LIST,
        {"news_items": [_news_item_minimal()]},
        context="unit-test",
    )
    assert len(from_items_list) == 1
    assert from_items_list[0]["id"] == "n1"

    from_report = parse_news_items_for_debate(
        ARTIFACT_KIND_NEWS_ANALYSIS_REPORT,
        {
            "ticker": "AAPL",
            "overall_sentiment": "bullish",
            "sentiment_score": 0.8,
            "key_themes": [],
            "news_items": [],
        },
        context="unit-test",
    )
    assert from_report == []
