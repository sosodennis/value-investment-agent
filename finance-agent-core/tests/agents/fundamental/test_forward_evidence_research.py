from datetime import UTC, datetime
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
    FundamentalForwardEvidenceReviewResultV1,
    FundamentalForwardEvidenceUsageV1,
)
from src.llm_provider.entrypoint import ModelRoute
from src.search.contracts import SearchOperationResult, SearchResult
from src.shared.internal_services import InternalPrincipal


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
    def __init__(self):
        self.calls: list[dict[str, object]] = []

    async def review_forward_evidence(self, input_payload, **_kwargs):
        self.calls.append(dict(input_payload))
        return FundamentalForwardEvidenceReviewResultV1(
            contract_version="fundamental.v1",
            status="prepared",
            label="forward-looking external evidence",
            policy_version="forward-evidence-policy-v1",
            automatic_preparation_digest="a" * 64,
            budget=FundamentalForwardEvidenceBudgetPolicyV1(),
            usage=FundamentalForwardEvidenceUsageV1(),
            reference_digest="b" * 64,
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
        deadline_at=datetime(2026, 11, 11, 0, 1, tzinfo=UTC),
    )

    assert result.status == "prepared"
    assert llm.calls == 1
    assert len(fundamental.calls) == 1
    assert fundamental.calls[0]["opt_in"] is True
    assert fundamental.calls[0]["claims"]
    assert fundamental.calls[0]["usage"]["search_queries"] == 1
    assert fundamental.calls[0]["usage"]["source_fetches"] == 0
    assert fundamental.calls[0]["budget"]["max_duration_ms"] == 15000


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
        deadline_at=datetime(2026, 11, 11, 0, 1, tzinfo=UTC),
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
        deadline_at=datetime(2026, 11, 11, 0, 1, tzinfo=UTC),
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
        deadline_at=datetime(2026, 11, 11, 0, 1, tzinfo=UTC),
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
        deadline_at=datetime(2026, 10, 31, 23, 59, tzinfo=UTC),
    )

    assert result.status == "unavailable"
    assert result.issue_codes == ("DEADLINE_EXCEEDED",)
    assert search_calls == 0
    assert llm.calls == 0
    assert fundamental.calls == []
