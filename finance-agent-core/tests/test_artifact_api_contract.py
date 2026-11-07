from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import httpx
import pytest

from api.server import app
from src.agents.debate.interface.contracts import parse_debate_artifact_model
from src.agents.news.interface.contracts import parse_news_artifact_model
from src.agents.technical.interface.contracts import parse_technical_artifact_model
from src.artifacts.application.wiring import build_default_artifact_service
from src.artifacts.public import (
    ARTIFACT_KIND_FINANCIAL_REPORTS,
    build_artifact_envelope,
    parse_artifact_data_json,
)
from src.auth.entrypoint import Principal, require_current_user


@dataclass(frozen=True)
class ArtifactApiDoubles:
    service: AsyncMock
    ownership: AsyncMock


@pytest.fixture
def authenticated_api(monkeypatch: pytest.MonkeyPatch) -> ArtifactApiDoubles:
    app.dependency_overrides[require_current_user] = lambda: Principal(
        user_id="test-user",
        subject="test-user",
        email="test@example.com",
        organization_id="organization-test",
        membership_id="membership-test",
    )
    service = AsyncMock()
    service.get_artifact_thread_id.return_value = "test-thread"
    service.get_run_thread_id.return_value = "test-thread"
    service.belongs_to_organization.return_value = True
    service.is_agent_output_reference.return_value = False
    service.is_referenced_artifact_reference.return_value = False
    service.is_agent_output_for_run.return_value = True
    service.is_referenced_artifact_for_run.return_value = False

    ownership = AsyncMock()
    ownership.owns.return_value = True
    monkeypatch.setattr(
        "src.artifacts.interface.routes.get_ownership_service",
        lambda: ownership,
    )
    app.dependency_overrides[build_default_artifact_service] = lambda: service
    yield ArtifactApiDoubles(service=service, ownership=ownership)
    app.dependency_overrides.clear()


async def _get_artifact(
    artifact_id: str,
    *,
    run_id: str | None = None,
) -> httpx.Response:
    params = {} if run_id is None else {"run_id": run_id}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        return await client.get(f"/api/v1/artifacts/{artifact_id}", params=params)


def _news_payload() -> dict[str, object]:
    return {
        "ticker": "AAPL",
        "news_items": [],
        "overall_sentiment": "neutral",
        "sentiment_score": 0.0,
        "key_themes": [],
    }


@pytest.mark.asyncio
async def test_get_artifact_preserves_versioned_api_response_and_empty_payload(
    authenticated_api: ArtifactApiDoubles,
) -> None:
    envelope = build_artifact_envelope(
        kind="news_analysis_report",
        produced_by="tests",
        data=parse_news_artifact_model(_news_payload()),
    )
    authenticated_api.service.get_artifact_envelope.return_value = envelope

    response = await _get_artifact("art_news")

    assert response.status_code == 200
    assert response.json()["kind"] == "news_analysis_report"
    assert response.json()["version"] == "v1"
    assert response.json()["data"]["news_items"] == []
    assert response.headers["cache-control"] == "private, max-age=3600"
    assert response.headers["etag"] == '"art_news"'
    authenticated_api.ownership.owns.assert_awaited_once_with(
        user_id="test-user",
        resource_type="thread",
        resource_id="test-thread",
    )


@pytest.mark.asyncio
async def test_get_artifact_returns_canonical_fundamental_news_debate_and_technical_data(
    authenticated_api: ArtifactApiDoubles,
) -> None:
    fundamental = parse_artifact_data_json(
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
        context="test.financial_reports",
    )
    news = parse_news_artifact_model(_news_payload())
    debate = parse_debate_artifact_model(
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
    technical = parse_technical_artifact_model(
        {
            "schema_version": "2.0",
            "ticker": "TSLA",
            "as_of": "2026-02-12T12:00:00Z",
            "direction": "BULLISH_EXTENSION",
            "risk_level": "medium",
            "confidence": 0.66,
            "llm_interpretation": "Trend remains constructive.",
            "artifact_refs": {"chart_data_id": "chart-1"},
            "summary_tags": ["TREND_ACTIVE"],
            "diagnostics": {"is_degraded": False, "degraded_reasons": []},
        }
    )

    for artifact_id, kind, payload, expected_key in (
        ("art_fa", "financial_reports", fundamental, "financial_reports"),
        ("art_news", "news_analysis_report", news, "news_items"),
        ("art_debate", "debate_final_report", debate, "final_verdict"),
        ("art_ta", "ta_full_report", technical, "artifact_refs"),
    ):
        authenticated_api.service.get_artifact_envelope.return_value = (
            build_artifact_envelope(
                kind=kind,
                produced_by="tests",
                data=payload,
            )
        )
        response = await _get_artifact(artifact_id)
        assert response.status_code == 200
        assert response.json()["kind"] == kind
        assert expected_key in response.json()["data"]


@pytest.mark.asyncio
async def test_run_scoped_artifact_checks_owner_before_reference_and_payload_reads(
    authenticated_api: ArtifactApiDoubles,
) -> None:
    calls: list[str] = []

    async def run_thread(**_: object) -> str:
        calls.append("run")
        return "test-thread"

    async def owns(**_: object) -> bool:
        calls.append("owner")
        return True

    async def artifact_thread(_: str) -> str:
        calls.append("artifact_thread")
        return "test-thread"

    async def direct_reference(**_: object) -> bool:
        calls.append("reference")
        return True

    async def read_envelope(_: str):
        calls.append("payload")
        return build_artifact_envelope(
            kind="news_analysis_report",
            produced_by="tests",
            data=_news_payload(),
        )

    authenticated_api.service.get_run_thread_id.side_effect = run_thread
    authenticated_api.ownership.owns.side_effect = owns
    authenticated_api.service.get_artifact_thread_id.side_effect = artifact_thread
    authenticated_api.service.is_agent_output_for_run.side_effect = direct_reference
    authenticated_api.service.get_artifact_envelope.side_effect = read_envelope

    response = await _get_artifact("art_output", run_id="run-output")

    assert response.status_code == 200
    assert calls == ["run", "owner", "artifact_thread", "reference", "payload"]
    authenticated_api.service.get_run_thread_id.assert_awaited_once_with(
        run_id="run-output",
        organization_id="organization-test",
    )
    authenticated_api.service.get_artifact_thread_id.assert_awaited_once_with(
        "art_output"
    )


@pytest.mark.asyncio
async def test_run_scoped_child_reference_is_checked_after_owner(
    authenticated_api: ArtifactApiDoubles,
) -> None:
    authenticated_api.service.get_artifact_thread_id.return_value = None
    envelope = build_artifact_envelope(
        kind="news_analysis_report",
        produced_by="tests",
        data=_news_payload(),
    )
    authenticated_api.service.is_agent_output_for_run.return_value = False
    authenticated_api.service.is_referenced_artifact_for_run.return_value = True
    authenticated_api.service.get_artifact_envelope.return_value = envelope

    response = await _get_artifact("child-artifact", run_id="run-output")

    assert response.status_code == 200
    authenticated_api.ownership.owns.assert_awaited_once()
    authenticated_api.service.is_referenced_artifact_for_run.assert_awaited_once_with(
        artifact_id="child-artifact",
        thread_id="test-thread",
        run_id="run-output",
    )


@pytest.mark.parametrize("reference_kind", ["direct", "child"])
@pytest.mark.asyncio
async def test_run_scoped_reference_cannot_read_artifact_from_another_thread(
    authenticated_api: ArtifactApiDoubles,
    reference_kind: str,
) -> None:
    authenticated_api.service.get_artifact_thread_id.return_value = "other-thread"
    if reference_kind == "child":
        authenticated_api.service.is_agent_output_for_run.return_value = False
        authenticated_api.service.is_referenced_artifact_for_run.return_value = True

    response = await _get_artifact("cross-thread-artifact", run_id="run-output")

    assert response.status_code == 404
    authenticated_api.ownership.owns.assert_awaited_once()
    authenticated_api.service.get_artifact_thread_id.assert_awaited_once_with(
        "cross-thread-artifact"
    )
    authenticated_api.service.is_agent_output_for_run.assert_not_awaited()
    authenticated_api.service.is_referenced_artifact_for_run.assert_not_awaited()
    authenticated_api.service.get_artifact_envelope.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_scoped_threadless_output_is_available_through_its_run_reference(
    authenticated_api: ArtifactApiDoubles,
) -> None:
    authenticated_api.service.get_artifact_thread_id.return_value = None
    authenticated_api.service.get_artifact_envelope.return_value = (
        build_artifact_envelope(
            kind="news_analysis_report",
            produced_by="tests",
            data=_news_payload(),
        )
    )

    response = await _get_artifact("threadless-output", run_id="run-output")

    assert response.status_code == 200
    authenticated_api.service.is_agent_output_for_run.assert_awaited_once_with(
        artifact_id="threadless-output",
        thread_id="test-thread",
        run_id="run-output",
    )


@pytest.mark.asyncio
async def test_organization_or_user_mismatch_returns_safe_404_before_payload_read(
    authenticated_api: ArtifactApiDoubles,
) -> None:
    authenticated_api.service.belongs_to_organization.return_value = False
    response = await _get_artifact("tenant-private")

    assert response.status_code == 404
    assert response.json() == {"detail": "artifact_not_found"}
    authenticated_api.ownership.owns.assert_not_awaited()
    authenticated_api.service.is_agent_output_reference.assert_not_awaited()
    authenticated_api.service.get_artifact_envelope.assert_not_awaited()

    authenticated_api.service.belongs_to_organization.return_value = True
    authenticated_api.ownership.owns.return_value = False
    response = await _get_artifact("user-private")

    assert response.status_code == 404
    authenticated_api.service.is_agent_output_reference.assert_not_awaited()
    authenticated_api.service.get_artifact_envelope.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_organization_or_user_mismatch_returns_404_before_payload_read(
    authenticated_api: ArtifactApiDoubles,
) -> None:
    authenticated_api.service.get_run_thread_id.return_value = None
    response = await _get_artifact("private", run_id="foreign-run")

    assert response.status_code == 404
    authenticated_api.ownership.owns.assert_not_awaited()
    authenticated_api.service.is_agent_output_for_run.assert_not_awaited()
    authenticated_api.service.get_artifact_envelope.assert_not_awaited()

    authenticated_api.service.get_run_thread_id.return_value = "test-thread"
    authenticated_api.ownership.owns.return_value = False
    response = await _get_artifact("private", run_id="user-private-run")

    assert response.status_code == 404
    authenticated_api.service.is_agent_output_for_run.assert_not_awaited()
    authenticated_api.service.is_referenced_artifact_for_run.assert_not_awaited()
    authenticated_api.service.get_artifact_envelope.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_artifact_and_unlisted_references_remain_hidden(
    authenticated_api: ArtifactApiDoubles,
) -> None:
    authenticated_api.service.get_artifact_thread_id.return_value = None
    response = await _get_artifact("missing")
    assert response.status_code == 404
    authenticated_api.ownership.owns.assert_not_awaited()

    authenticated_api.service.get_artifact_thread_id.return_value = "test-thread"
    authenticated_api.service.is_agent_output_reference.return_value = True
    response = await _get_artifact("output-without-run")
    assert response.status_code == 404
    authenticated_api.service.get_artifact_envelope.assert_not_awaited()

    authenticated_api.service.is_agent_output_reference.return_value = False
    authenticated_api.service.is_agent_output_for_run.return_value = False
    response = await _get_artifact("unlisted", run_id="wrong-run")
    assert response.status_code == 404
    authenticated_api.service.get_artifact_envelope.assert_not_awaited()
