from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from api.server import app
from src.interface.artifact_envelope import build_artifact_envelope
from src.interface.canonical_serializers import (
    canonicalize_debate_artifact_data,
    canonicalize_fundamental_artifact_data,
    canonicalize_news_artifact_data,
    canonicalize_technical_artifact_data,
)


@pytest.mark.asyncio
async def test_get_artifact_returns_canonical_fundamental_payload() -> None:
    payload = canonicalize_fundamental_artifact_data(
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
        }
    )
    envelope = build_artifact_envelope(
        kind="financial_reports",
        produced_by="tests",
        data=payload,
    )
    with patch(
        "api.server.artifact_manager.get_artifact_envelope",
        new=AsyncMock(return_value=envelope),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/artifacts/art_fa")

    assert response.status_code == 200
    assert response.json()["kind"] == "financial_reports"
    assert response.json()["data"]["company_name"] == "AAPL"
    assert (
        response.json()["data"]["financial_reports"][0]["base"]["fiscal_year"]["value"]
        == "2024"
    )
    assert response.headers["cache-control"] == "public, max-age=3600"
    assert response.headers["etag"] == '"art_fa"'


@pytest.mark.asyncio
async def test_get_artifact_returns_canonical_news_and_debate_payload() -> None:
    news_payload = canonicalize_news_artifact_data(
        {
            "ticker": "NVDA",
            "news_items": [
                {
                    "id": "n1",
                    "url": "https://example.com/news",
                    "fetched_at": "2026-02-12T12:00:00Z",
                    "title": "Headline",
                    "snippet": "Snippet",
                    "source": {
                        "name": "Reuters",
                        "domain": "reuters.com",
                        "reliability_score": 0.9,
                    },
                    "related_tickers": [
                        {
                            "ticker": "NVDA",
                            "company_name": "NVIDIA",
                            "relevance_score": 0.95,
                        }
                    ],
                    "categories": ["trusted_news", "bullish"],
                    "tags": ["earnings"],
                    "analysis": {
                        "summary": "Positive",
                        "sentiment": "bullish",
                        "sentiment_score": 0.8,
                        "impact_level": "high",
                        "reasoning": "Beat guidance",
                        "key_facts": [
                            {
                                "content": "Revenue up",
                                "is_quantitative": True,
                                "sentiment": "bullish",
                            }
                        ],
                    },
                }
            ],
            "overall_sentiment": "bullish",
            "sentiment_score": 0.8,
            "key_themes": ["AI demand"],
        }
    )

    debate_payload = canonicalize_debate_artifact_data(
        {
            "scenario_analysis": {
                "bull_case": {
                    "probability": 55,
                    "outcome_description": "Upside",
                    "price_implication": "SURGE",
                },
                "bear_case": {
                    "probability": 20,
                    "outcome_description": "Downside",
                    "price_implication": "CRASH",
                },
                "base_case": {
                    "probability": 25,
                    "outcome_description": "Rangebound",
                    "price_implication": "FLAT",
                },
            },
            "risk_profile": "GROWTH_TECH",
            "final_verdict": "LONG",
            "winning_thesis": "Growth re-acceleration",
            "primary_catalyst": "Product cycle",
            "primary_risk": "Multiple compression",
            "supporting_factors": ["Demand resilience"],
            "debate_rounds": 3,
        }
    )

    technical_payload = canonicalize_technical_artifact_data(
        {
            "ticker": "TSLA",
            "timestamp": "2026-02-12T12:00:00Z",
            "frac_diff_metrics": {
                "optimal_d": 0.41,
                "window_length": 252,
                "adf_statistic": -3.2,
                "adf_pvalue": 0.01,
                "memory_strength": "balanced",
            },
            "signal_state": {
                "z_score": 1.2,
                "statistical_state": "deviating",
                "direction": "BULLISH_EXTENSION",
                "risk_level": "medium",
                "confluence": {
                    "bollinger_state": "INSIDE",
                    "macd_momentum": "BULLISH_EXPANDING",
                    "obv_state": "ACCUMULATING",
                    "statistical_strength": 62.3,
                },
            },
            "semantic_tags": ["TREND_ACTIVE"],
        }
    )

    for artifact_id, kind, payload, expected_key in (
        ("art_news", "news_analysis_report", news_payload, "overall_sentiment"),
        ("art_debate", "debate_final_report", debate_payload, "final_verdict"),
        ("art_ta", "ta_full_report", technical_payload, "signal_state"),
    ):
        envelope = build_artifact_envelope(
            kind=kind,
            produced_by="tests",
            data=payload,
        )
        with patch(
            "api.server.artifact_manager.get_artifact_envelope",
            new=AsyncMock(return_value=envelope),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
            ) as client:
                response = await client.get(f"/api/artifacts/{artifact_id}")

        assert response.status_code == 200
        assert response.json()["kind"] == kind
        assert expected_key in response.json()["data"]


@pytest.mark.asyncio
async def test_get_artifact_returns_404_when_missing() -> None:
    with patch(
        "api.server.artifact_manager.get_artifact_envelope",
        new=AsyncMock(return_value=None),
    ):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/artifacts/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Artifact not found"}
