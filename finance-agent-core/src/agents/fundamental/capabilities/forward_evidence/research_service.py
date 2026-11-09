from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
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
from src.llm_provider.application.context import (
    reset_provider_principal,
    set_provider_principal,
)
from src.llm_provider.domain.contracts import ProviderPrincipal
from src.llm_provider.entrypoint import (
    ChatMessage,
    ChatRole,
    CompletionRequest,
    LLMProviderPort,
    LLMRequestClass,
    ModelRoute,
    StructuredRequest,
)
from src.search.contracts import WebSearchRequest
from src.shared.internal_services import (
    InternalPrincipal,
    reset_request_principal,
    set_request_principal,
)


@dataclass(frozen=True)
class ForwardEvidenceResearchService:
    fundamental_service_client: FundamentalServiceClient
    search_fn: Callable[[WebSearchRequest], object]
    llm_provider: LLMProviderPort
    llm_route: ModelRoute
    search_result_limit: int = 5
    request_timeout_seconds: float = 15.0

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
            try:
                raw_search = await asyncio.to_thread(
                    self.search_fn,
                    WebSearchRequest(
                        query=query,
                        result_limit=self.search_result_limit,
                    ),
                )
                results = tuple(getattr(raw_search, "results", ()))
            except Exception:
                return self._unavailable(
                    request,
                    budget=budget,
                    code="SEARCH_PROVIDER_FAILURE",
                    elapsed_ms=int((monotonic() - started) * 1000),
                )

            source_payloads = [
                {
                    "title": item.title,
                    "source_url": item.canonical_url,
                    "publisher": item.source or item.provider,
                    "published_at": item.published_at.isoformat()
                    if item.published_at
                    else None,
                    "snippet": item.snippet,
                    "provider": item.provider,
                }
                for item in results[: self.search_result_limit]
            ]
            if not source_payloads:
                return self._unavailable(
                    request,
                    budget=budget,
                    code="SEARCH_NO_RESULTS",
                    elapsed_ms=int((monotonic() - started) * 1000),
                )

            prompt = (
                "Extract only numeric forward-looking claims relevant to the "
                "requested assumption path. Every claim must quote a direct source "
                "passage, retain the exact source URL, and use a future fiscal "
                "period. Do not infer or average values. Return an empty claims "
                "array when evidence is unsupported or ambiguous.\n\n"
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
                extraction = await self.llm_provider.acomplete_structured(llm_request)
            except Exception:
                return self._unavailable(
                    request,
                    budget=budget,
                    code="LLM_PROVIDER_FAILURE",
                    elapsed_ms=int((monotonic() - started) * 1000),
                    search_results=len(source_payloads),
                    llm_input_bytes=len(prompt.encode("utf-8")),
                )

            claims = self._build_claims(request, extraction, source_payloads)
            service_request = {
                "contract_version": "fundamental.v1",
                "opt_in": True,
                "ticker": request.ticker,
                "issuer_id": request.issuer_id,
                "model_id": request.model_id,
                "assumption_path": request.assumption_path,
                "valuation_timestamp": request.valuation_timestamp,
                "automatic_preparation_digest": request.automatic_preparation_digest,
                "claims": [claim.model_dump(mode="json") for claim in claims],
                "budget": budget.model_dump(mode="json"),
                "usage": FundamentalForwardEvidenceUsageV1(
                    search_queries=1,
                    search_results=len(source_payloads),
                    source_fetches=len(source_payloads),
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
                return self._unavailable(
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
        source_payloads: Sequence[dict[str, object]],
    ) -> tuple[FundamentalForwardEvidenceClaimV1, ...]:
        by_url = {str(item["source_url"]): item for item in source_payloads}
        claims: list[FundamentalForwardEvidenceClaimV1] = []
        for index, draft in enumerate(extraction.claims):
            source = by_url.get(draft.source_url)
            published_at = (
                datetime.fromisoformat(str(source["published_at"]))
                if source and source.get("published_at")
                else request.valuation_timestamp
            )
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=UTC)
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
                    period_end=datetime.fromisoformat(draft.period_end).date(),
                    extraction_method="llm_from_source_passage",
                    source=FundamentalForwardEvidenceSourceV1(
                        source_id=(
                            str(source["source_url"]) if source else draft.source_url
                        ),
                        source_url=draft.source_url,
                        publisher=(str(source["publisher"]) if source else "unknown"),
                        source_type=draft.source_type,
                        retained_passage=draft.source_passage,
                        content_hash=passage_hash,
                        published_at=published_at,
                        retrieved_at=request.valuation_timestamp,
                        license_status=draft.license_status,
                        license_reference=draft.license_reference,
                    ),
                    status="accepted",
                )
            )
        return tuple(claims)

    @staticmethod
    def _unavailable(
        request: ForwardEvidenceResearchRequest,
        *,
        budget: FundamentalForwardEvidenceBudgetPolicyV1,
        code: str,
        elapsed_ms: int,
        search_results: int = 0,
        llm_input_bytes: int = 0,
    ) -> FundamentalForwardEvidenceReviewResultV1:
        usage = FundamentalForwardEvidenceUsageV1(
            search_queries=1 if code != "SEARCH_PROVIDER_FAILURE" else 0,
            search_results=search_results,
            llm_calls=1
            if code in {"LLM_PROVIDER_FAILURE", "FUNDAMENTAL_SERVICE_FAILURE"}
            else 0,
            llm_input_bytes=llm_input_bytes,
            elapsed_ms=elapsed_ms,
        )
        payload = {
            "status": "unavailable",
            "label": "forward-looking external evidence",
            "policy_version": budget.policy_version,
            "automatic_preparation_digest": request.automatic_preparation_digest,
            "claims": (),
            "accepted_claim_ids": (),
            "excluded_claim_ids": (),
            "issue_codes": (code,),
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
