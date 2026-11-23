from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Literal
from uuid import uuid4

from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceClient,
    FundamentalServiceFailure,
)
from src.agents.fundamental.capabilities.forward_evidence.contracts import (
    ForwardEvidenceExtraction,
    ForwardEvidenceResearchRequest,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalForwardEvidenceBudgetPolicyV1,
    FundamentalForwardEvidenceClaimV1,
    FundamentalForwardEvidenceReviewResultV1,
    FundamentalForwardEvidenceSourceV1,
    FundamentalForwardEvidenceUsageV1,
)
from src.llm_provider.entrypoint import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    LLMProviderPort,
    LLMRequestClass,
    ModelRoute,
    ProviderPrincipal,
    StructuredRequest,
    reset_provider_principal,
    set_provider_principal,
)
from src.search.contracts import SearchOperationResult, SearchResult, WebSearchRequest
from src.shared.internal_services import (
    InternalPrincipal,
    reset_request_principal,
    set_request_principal,
)


@dataclass(frozen=True)
class _SourceBoundClaims:
    claims: tuple[FundamentalForwardEvidenceClaimV1, ...]
    issue_codes: tuple[str, ...]


@dataclass(frozen=True)
class ForwardEvidenceResearchService:
    fundamental_service_client: FundamentalServiceClient
    search_fn: Callable[[WebSearchRequest], SearchOperationResult]
    llm_provider: LLMProviderPort
    llm_route: ModelRoute
    search_result_limit: int = 5
    request_timeout_seconds: float = 15.0

    def __post_init__(self) -> None:
        if self.search_result_limit < 1 or self.search_result_limit > 5:
            raise ValueError("search_result_limit must be between 1 and 5")
        if self.request_timeout_seconds < 0.5 or self.request_timeout_seconds > 120:
            raise ValueError("request_timeout_seconds must be between 0.5 and 120")

    async def research(
        self,
        request: ForwardEvidenceResearchRequest,
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalForwardEvidenceReviewResultV1:
        started = monotonic()
        budget = FundamentalForwardEvidenceBudgetPolicyV1(
            max_results_per_query=self.search_result_limit,
            max_duration_ms=int(self.request_timeout_seconds * 1000),
        )
        principal_token = set_request_principal(principal)
        provider_token = set_provider_principal(
            ProviderPrincipal(
                user_id=principal.subject_id,
                organization_id=principal.organization_id or "unscoped",
                membership_id=principal.membership_id or "unscoped",
            )
        )
        try:
            query = f"{request.ticker} {request.question} {request.assumption_path}"
            remaining = max(
                0.0,
                (deadline_at.astimezone(UTC) - datetime.now(UTC)).total_seconds(),
            )
            if remaining <= 0:
                return self._without_claims(
                    request,
                    budget=budget,
                    code="DEADLINE_EXCEEDED",
                    elapsed_ms=int((monotonic() - started) * 1000),
                )
            try:
                raw_search = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.search_fn,
                        WebSearchRequest(
                            query=query,
                            result_limit=self.search_result_limit,
                        ),
                    ),
                    timeout=min(self.request_timeout_seconds, remaining),
                )
            except asyncio.TimeoutError:
                return self._without_claims(
                    request,
                    budget=budget,
                    code="DEADLINE_EXCEEDED",
                    elapsed_ms=int((monotonic() - started) * 1000),
                )
            except Exception:
                return self._without_claims(
                    request,
                    budget=budget,
                    code="SEARCH_PROVIDER_FAILURE",
                    elapsed_ms=int((monotonic() - started) * 1000),
                )
            results = raw_search.results
            retrieved_at = datetime.now(UTC)

            source_payloads: list[dict[str, object]] = []
            sources: list[SearchResult] = []
            source_bytes = 0
            for item in results[: self.search_result_limit]:
                candidate = {
                    "title": item.title,
                    "source_url": item.canonical_url,
                    "publisher": item.source or item.provider,
                    "published_at": item.published_at.isoformat()
                    if item.published_at
                    else None,
                    "snippet": item.snippet,
                    "provider": item.provider,
                }
                candidate_bytes = len(
                    json.dumps(
                        candidate, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")
                )
                if source_bytes + candidate_bytes > budget.max_source_bytes:
                    continue
                source_payloads.append(candidate)
                sources.append(item)
                source_bytes += candidate_bytes
            if not source_payloads:
                return self._without_claims(
                    request,
                    budget=budget,
                    code="SOURCE_BUDGET_EXCEEDED" if results else "SEARCH_NO_RESULTS",
                    elapsed_ms=int((monotonic() - started) * 1000),
                )

            prompt = (
                "Extract only numeric forward-looking claims relevant to the "
                "requested assumption path. Every claim must quote a direct source "
                "passage, retain the exact source URL, and use a future fiscal "
                "period. The available sources are search discovery snippets, not "
                "retained full text. Quote an exact substring of a supplied snippet. "
                "Do not infer source permissions. Do not infer or average numeric "
                "values. Return an empty claims array when evidence is unsupported "
                "or ambiguous.\n\n"
                f"Request: {request.model_dump_json()}\n"
                f"Search sources: {json.dumps(source_payloads, ensure_ascii=False)}"
            )
            llm_request = StructuredRequest(
                completion=CompletionRequest(
                    messages=(
                        ChatMessage(
                            role=ChatRole.SYSTEM,
                            content="You are a source-bound financial evidence extractor.",
                        ),
                        ChatMessage(role=ChatRole.USER, content=prompt),
                    ),
                    route=self.llm_route,
                    request_id=f"forward-evidence-{uuid4().hex}",
                    operation="fundamental.forward_evidence.extract",
                    request_class=LLMRequestClass.INTERACTIVE,
                    temperature=0.0,
                    max_tokens=1800,
                    timeout_seconds=self.request_timeout_seconds,
                ),
                response_schema=ForwardEvidenceExtraction,
            )
            try:
                remaining = max(
                    0.0,
                    (deadline_at.astimezone(UTC) - datetime.now(UTC)).total_seconds(),
                )
                extraction = await asyncio.wait_for(
                    self.llm_provider.acomplete_structured(llm_request),
                    timeout=min(self.request_timeout_seconds, remaining),
                )
            except asyncio.TimeoutError:
                return self._without_claims(
                    request,
                    budget=budget,
                    code="DEADLINE_EXCEEDED",
                    elapsed_ms=int((monotonic() - started) * 1000),
                    search_results=len(source_payloads),
                    llm_input_bytes=len(prompt.encode("utf-8")),
                )
            except Exception:
                return self._without_claims(
                    request,
                    budget=budget,
                    code="LLM_PROVIDER_FAILURE",
                    elapsed_ms=int((monotonic() - started) * 1000),
                    search_results=len(source_payloads),
                    llm_input_bytes=len(prompt.encode("utf-8")),
                )

            candidates = self._build_claims(
                request,
                extraction,
                sources,
                max_claims=budget.max_llm_claims,
                retrieved_at=retrieved_at,
            )
            if candidates.issue_codes:
                return self._without_claims(
                    request,
                    budget=budget,
                    code=candidates.issue_codes[0],
                    additional_issue_codes=candidates.issue_codes[1:],
                    status="unsupported",
                    elapsed_ms=int((monotonic() - started) * 1000),
                    search_results=len(source_payloads),
                    llm_input_bytes=len(prompt.encode("utf-8")),
                )
            service_request = {
                "contract_version": "fundamental.v1",
                "opt_in": True,
                "ticker": request.ticker,
                "issuer_id": request.issuer_id,
                "model_id": request.model_id,
                "assumption_path": request.assumption_path,
                "valuation_timestamp": request.valuation_timestamp.isoformat(),
                "automatic_preparation_digest": request.automatic_preparation_digest,
                "claims": [
                    claim.model_dump(mode="json") for claim in candidates.claims
                ],
                "budget": budget.model_dump(mode="json"),
                "usage": FundamentalForwardEvidenceUsageV1(
                    search_queries=1,
                    search_results=len(source_payloads),
                    source_fetches=0,
                    llm_calls=1,
                    llm_input_bytes=len(prompt.encode("utf-8")),
                    elapsed_ms=int((monotonic() - started) * 1000),
                ).model_dump(mode="json"),
            }
            try:
                return await self.fundamental_service_client.review_forward_evidence(
                    service_request,
                    principal=principal,
                    correlation_id=correlation_id,
                    deadline_at=deadline_at,
                )
            except FundamentalServiceFailure:
                return self._without_claims(
                    request,
                    budget=budget,
                    code="FUNDAMENTAL_SERVICE_FAILURE",
                    elapsed_ms=int((monotonic() - started) * 1000),
                    search_results=len(source_payloads),
                    llm_input_bytes=len(prompt.encode("utf-8")),
                )
        finally:
            reset_provider_principal(provider_token)
            reset_request_principal(principal_token)

    @staticmethod
    def _build_claims(
        request: ForwardEvidenceResearchRequest,
        extraction: ForwardEvidenceExtraction,
        sources: Sequence[SearchResult],
        *,
        max_claims: int,
        retrieved_at: datetime,
    ) -> _SourceBoundClaims:
        by_url = {item.canonical_url: item for item in sources}
        claims: list[FundamentalForwardEvidenceClaimV1] = []
        issue_codes: list[str] = []
        for index, draft in enumerate(extraction.claims[:max_claims]):
            source = by_url.get(draft.source_url)
            if source is None:
                issue_codes.append("SOURCE_NOT_IN_SEARCH_INVENTORY")
                continue
            if draft.source_passage not in source.snippet:
                issue_codes.append("SOURCE_PASSAGE_NOT_RETAINED")
                continue
            if source.published_at is None:
                issue_codes.append("SOURCE_PUBLICATION_DATE_MISSING")
                continue
            publisher = source.source or source.provider
            if not publisher.strip():
                issue_codes.append("SOURCE_PUBLISHER_MISSING")
                continue
            try:
                period_end = datetime.fromisoformat(draft.period_end).date()
            except ValueError:
                issue_codes.append("CLAIM_PERIOD_INVALID")
                continue
            passage_hash = hashlib.sha256(
                draft.source_passage.encode("utf-8")
            ).hexdigest()
            claims.append(
                FundamentalForwardEvidenceClaimV1(
                    claim_id=f"forward-{index + 1}-{passage_hash[:12]}",
                    issuer_id=request.issuer_id,
                    ticker=request.ticker,
                    model_id=request.model_id,
                    metric=draft.metric,
                    assumption_path=draft.assumption_path or request.assumption_path,
                    value=draft.value,
                    unit=draft.unit,
                    fiscal_period=draft.fiscal_period,
                    period_type=draft.period_type,
                    period_end=period_end,
                    extraction_method="llm_from_source_passage",
                    source=FundamentalForwardEvidenceSourceV1(
                        source_id="search-"
                        + hashlib.sha256(
                            source.canonical_url.encode("utf-8")
                        ).hexdigest(),
                        source_url=source.canonical_url,
                        publisher=publisher,
                        source_type="search_discovery",
                        retained_passage=draft.source_passage,
                        content_hash=passage_hash,
                        published_at=source.published_at,
                        retrieved_at=retrieved_at,
                        license_status="unknown",
                        license_reference=None,
                    ),
                    status="excluded",
                    issue_codes=("SOURCE_LICENSE_NOT_APPROVED",),
                    exclusion_reasons=(
                        "Search discovery does not establish source usage rights.",
                    ),
                )
            )
        return _SourceBoundClaims(tuple(claims), tuple(dict.fromkeys(issue_codes)))

    @staticmethod
    def _without_claims(
        request: ForwardEvidenceResearchRequest,
        *,
        budget: FundamentalForwardEvidenceBudgetPolicyV1,
        code: str,
        elapsed_ms: int,
        additional_issue_codes: tuple[str, ...] = (),
        status: Literal["unsupported", "unavailable"] = "unavailable",
        search_results: int = 0,
        llm_input_bytes: int = 0,
    ) -> FundamentalForwardEvidenceReviewResultV1:
        usage = FundamentalForwardEvidenceUsageV1(
            search_queries=1 if code != "SEARCH_PROVIDER_FAILURE" else 0,
            search_results=search_results,
            llm_calls=1 if llm_input_bytes else 0,
            llm_input_bytes=llm_input_bytes,
            elapsed_ms=elapsed_ms,
        )
        payload = {
            "status": status,
            "label": "forward-looking external evidence",
            "policy_version": budget.policy_version,
            "automatic_preparation_digest": request.automatic_preparation_digest,
            "claims": (),
            "accepted_claim_ids": (),
            "excluded_claim_ids": (),
            "issue_codes": (code, *additional_issue_codes),
            "budget": budget,
            "usage": usage,
        }
        digest = hashlib.sha256(
            json.dumps(
                {
                    key: value.model_dump(mode="json")
                    if hasattr(value, "model_dump")
                    else value
                    for key, value in payload.items()
                },
                sort_keys=True,
                default=str,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return FundamentalForwardEvidenceReviewResultV1(
            contract_version="fundamental.v1",
            **payload,
            reference_digest=digest,
        )
