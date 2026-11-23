import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from src.agents.fundamental.capabilities.forward_evidence.contracts import (
    ForwardEvidenceClaimDraft,
    ForwardEvidenceExtraction,
    ForwardEvidenceResearchRequest,
)
from src.agents.fundamental.capabilities.forward_evidence.research_service import (
    ForwardEvidenceResearchService,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalForwardEvidenceBudgetPolicyV1,
    FundamentalForwardEvidenceReviewRefV1,
    FundamentalForwardEvidenceReviewResultV1,
    FundamentalForwardEvidenceUsageV1,
)
from src.llm_provider.entrypoint import ModelRoute
from src.search.contracts import SearchOperationResult, SearchResult
from src.shared.internal_services import InternalPrincipal


def test_research_request_accepts_json_timestamp_and_normalizes_to_utc() -> None:
    request = ForwardEvidenceResearchRequest.model_validate(
        {
            "opt_in": True,
            "ticker": "AAPL",
            "issuer_id": "issuer-aapl",
            "model_id": "fcff_dcf",
            "assumption_path": "assumptions.forecast.revenue_growth[0]",
            "question": "What is the next annual revenue growth guidance?",
            "valuation_timestamp": "2026-11-10T00:55:00Z",
            "automatic_preparation_digest": "a" * 64,
        }
    )

    assert request.valuation_timestamp == datetime(2026, 11, 10, 0, 55, tzinfo=UTC)


def test_research_request_rejects_naive_json_timestamp() -> None:
    with pytest.raises(ValueError, match="must include a timezone"):
        ForwardEvidenceResearchRequest.model_validate(
            {
                "opt_in": True,
                "ticker": "AAPL",
                "issuer_id": "issuer-aapl",
                "model_id": "fcff_dcf",
                "assumption_path": "assumptions.forecast.revenue_growth[0]",
                "question": "What is the next annual revenue growth guidance?",
                "valuation_timestamp": "2026-11-10T00:55:00",
                "automatic_preparation_digest": "a" * 64,
            }
        )


def _request() -> ForwardEvidenceResearchRequest:
    return ForwardEvidenceResearchRequest(
        opt_in=True,
        ticker="AAPL",
        issuer_id="issuer-aapl",
        model_id="fcff_dcf",
        assumption_path="assumptions.forecast.revenue_growth[0]",
        question="What is the next annual revenue growth guidance?",
        valuation_timestamp=datetime(2026, 11, 1, tzinfo=UTC),
        automatic_preparation_digest="a" * 64,
    )


def _search_result(
    *, snippet: str = "Management expects revenue growth of 12 percent in fiscal 2027."
) -> SearchOperationResult:
    return SearchOperationResult(
        operation="web",
        results=(
            SearchResult(
                title="AAPL guidance",
                canonical_url="https://issuer.example/guidance",
                snippet=snippet,
                provider="fake-search",
                source="Issuer IR",
                published_at=datetime(2026, 10, 1, tzinfo=UTC),
            ),
        ),
    )


def _extraction() -> ForwardEvidenceExtraction:
    return ForwardEvidenceExtraction(
        claims=(
            ForwardEvidenceClaimDraft(
                metric="revenue_growth",
                assumption_path="assumptions.forecast.revenue_growth[0]",
                value=Decimal("0.12"),
                unit="ratio",
                fiscal_period="FY2027",
                period_type="annual",
                period_end="2027-09-30",
                source_url="https://issuer.example/guidance",
                source_passage="Management expects revenue growth of 12 percent in fiscal 2027.",
                source_type="issuer_guidance",
                license_status="approved",
                license_reference="issuer-terms-v1",
            ),
        ),
    )


class FakeLLM:
    def __init__(self, extraction: ForwardEvidenceExtraction | Exception):
        self.extraction = extraction
        self.calls = 0

    async def acomplete_structured(self, _request):
        self.calls += 1
        if isinstance(self.extraction, Exception):
            raise self.extraction
        return self.extraction


class FakeFundamentalService:
    def __init__(self, *, review_ref=None):
        self.calls: list[dict[str, object]] = []
        self.review_ref = review_ref

    async def review_forward_evidence(self, input_payload, **_kwargs):
        self.calls.append(dict(input_payload))
        return FundamentalForwardEvidenceReviewResultV1(
            contract_version="fundamental.v1",
            status="prepared",
            label="forward-looking external evidence",
            policy_version="forward-evidence-policy-v2",
            automatic_preparation_digest="a" * 64,
            budget=FundamentalForwardEvidenceBudgetPolicyV1(),
            usage=FundamentalForwardEvidenceUsageV1(),
            reference_digest="b" * 64,
            review_ref=self.review_ref,
        )


def _service(search_fn, llm, fundamental):
    return ForwardEvidenceResearchService(
        fundamental_service_client=fundamental,
        search_fn=search_fn,
        llm_provider=llm,
        llm_route=ModelRoute(alias="test-route"),
    )


@pytest.mark.anyio
async def test_research_calls_search_llm_and_service_only_after_opt_in() -> None:
    llm = FakeLLM(_extraction())
    fundamental = FakeFundamentalService()
    result = await _service(
        lambda _request: _search_result(), llm, fundamental
    ).research(
        _request(),
        principal=InternalPrincipal(
            subject_id="user-1", organization_id="org-1", membership_id="member-1"
        ),
        correlation_id="corr-1",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    assert result.status == "prepared"
    assert llm.calls == 1
    assert len(fundamental.calls) == 1
    assert fundamental.calls[0]["opt_in"] is True
    assert fundamental.calls[0]["claims"]
    assert fundamental.calls[0]["usage"]["search_queries"] == 1
    assert fundamental.calls[0]["usage"]["source_fetches"] == 0
    assert fundamental.calls[0]["budget"]["max_duration_ms"] == 15000
    assert (
        fundamental.calls[0]["budget"]["policy_version"] == "forward-evidence-policy-v2"
    )


@pytest.mark.anyio
async def test_terminal_growth_research_preserves_service_review_witness() -> None:
    request = _request().model_copy(
        update={"assumption_path": "assumptions.terminal_growth"}
    )
    extraction = ForwardEvidenceExtraction.model_validate(
        {
            "claims": (
                _extraction()
                .claims[0]
                .model_copy(
                    update={
                        "metric": "terminal_growth",
                        "assumption_path": "assumptions.terminal_growth",
                        "value": Decimal("0.025"),
                    }
                ),
            )
        }
    )
    review_ref = FundamentalForwardEvidenceReviewRefV1(
        artifact_id="forward-review-v1-" + "c" * 64, content_hash="c" * 64
    )
    fundamental = FakeFundamentalService(review_ref=review_ref)
    result = await _service(
        lambda _request: _search_result(), FakeLLM(extraction), fundamental
    ).research(
        request,
        principal=InternalPrincipal(
            subject_id="user-1", organization_id="org-1", membership_id="member-1"
        ),
        correlation_id="corr-terminal",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    assert fundamental.calls[0]["claims"][0]["metric"] == "terminal_growth"
    assert (
        fundamental.calls[0]["claims"][0]["assumption_path"]
        == "assumptions.terminal_growth"
    )
    wire = json.loads(json.dumps(fundamental.calls[0], allow_nan=False))
    assert wire["valuation_timestamp"] == "2026-11-01T00:00:00+00:00"
    assert wire["claims"][0]["value"] == "0.025"
    assert result.review_ref == review_ref
    assert (
        result.model_dump(mode="json")["review_ref"]["artifact_id"]
        == review_ref.artifact_id
    )


def test_legacy_review_without_witness_does_not_fabricate_one():
    result = FundamentalForwardEvidenceReviewResultV1(
        contract_version="fundamental.v1",
        status="prepared",
        label="forward-looking external evidence",
        policy_version="forward-evidence-policy-v2",
        automatic_preparation_digest="a" * 64,
        budget=FundamentalForwardEvidenceBudgetPolicyV1(),
        usage=FundamentalForwardEvidenceUsageV1(),
        reference_digest="b" * 64,
    )
    assert result.review_ref is None
    assert "review_ref" not in result.model_dump(mode="json")


@pytest.mark.parametrize(
    "field,value",
    [
        ("artifact_id", "untrusted-id"),
        ("content_hash", "not-a-digest"),
        ("media_type", "text/plain"),
        ("accepted", True),
    ],
)
def test_review_witness_reference_rejects_malformed_or_caller_status_fields(
    field, value
):
    payload = {"artifact_id": "forward-review-v1-" + "c" * 64, "content_hash": "c" * 64}
    payload[field] = value
    with pytest.raises(ValueError):
        FundamentalForwardEvidenceReviewRefV1.model_validate(payload)


@pytest.mark.anyio
async def test_search_failure_does_not_call_llm_or_fundamental_service() -> None:
    llm = FakeLLM(_extraction())
    fundamental = FakeFundamentalService()

    def fail(_request):
        raise RuntimeError("search unavailable")

    result = await _service(fail, llm, fundamental).research(
        _request(),
        principal=InternalPrincipal(
            subject_id="user-1", organization_id="org-1", membership_id="member-1"
        ),
        correlation_id="corr-1",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    assert result.status == "unavailable"
    assert result.issue_codes == ("SEARCH_PROVIDER_FAILURE",)
    assert llm.calls == 0
    assert fundamental.calls == []


@pytest.mark.anyio
async def test_llm_failure_is_optional_and_does_not_degrade_baseline() -> None:
    llm = FakeLLM(RuntimeError("provider unavailable"))
    fundamental = FakeFundamentalService()
    result = await _service(
        lambda _request: _search_result(), llm, fundamental
    ).research(
        _request(),
        principal=InternalPrincipal(
            subject_id="user-1", organization_id="org-1", membership_id="member-1"
        ),
        correlation_id="corr-1",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    assert result.status == "unavailable"
    assert result.issue_codes == ("LLM_PROVIDER_FAILURE",)
    assert fundamental.calls == []


@pytest.mark.anyio
async def test_source_budget_blocks_oversized_discovery_payload_before_llm() -> None:
    llm = FakeLLM(_extraction())
    fundamental = FakeFundamentalService()
    result = await _service(
        lambda _request: _search_result(snippet="x" * 200_000), llm, fundamental
    ).research(
        _request(),
        principal=InternalPrincipal(
            subject_id="user-1", organization_id="org-1", membership_id="member-1"
        ),
        correlation_id="corr-1",
        deadline_at=datetime.now(UTC) + timedelta(minutes=1),
    )

    assert result.status == "unavailable"
    assert result.issue_codes == ("SOURCE_BUDGET_EXCEEDED",)
    assert llm.calls == 0
    assert fundamental.calls == []


@pytest.mark.anyio
async def test_expired_deadline_skips_optional_providers() -> None:
    llm = FakeLLM(_extraction())
    fundamental = FakeFundamentalService()
    search_calls = 0

    def search(_request):
        nonlocal search_calls
        search_calls += 1
        return _search_result()

    result = await _service(search, llm, fundamental).research(
        _request(),
        principal=InternalPrincipal(
            subject_id="user-1", organization_id="org-1", membership_id="member-1"
        ),
        correlation_id="corr-1",
        deadline_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    assert result.status == "unavailable"
    assert result.issue_codes == ("DEADLINE_EXCEEDED",)
    assert search_calls == 0
    assert llm.calls == 0
    assert fundamental.calls == []
