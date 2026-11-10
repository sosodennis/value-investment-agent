from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.agents.fundamental.capabilities.forward_evidence import (
    ForwardEvidenceResearchRequest,
    ForwardEvidenceResearchService,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalForwardEvidenceReviewResultV1,
)
from src.auth.entrypoint import Principal, require_current_user_mutation
from src.shared.internal_services import InternalPrincipal


class ForwardEvidenceResearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: FundamentalForwardEvidenceReviewResultV1


def build_forward_evidence_router(
    service_factory: Callable[[], ForwardEvidenceResearchService],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/fundamental/forward-evidence",
        tags=["Fundamental forward evidence"],
    )

    @router.post("/research", response_model=ForwardEvidenceResearchResponse)
    async def research_forward_evidence(
        body: ForwardEvidenceResearchRequest,
        request: Request,
        principal: Principal = Depends(require_current_user_mutation),
    ) -> ForwardEvidenceResearchResponse:
        service = service_factory()
        correlation_id = request.headers.get("X-Request-ID") or str(uuid4())
        deadline_at = datetime.now(UTC) + timedelta(
            seconds=service.request_timeout_seconds + 2
        )
        try:
            result = await service.research(
                body,
                principal=InternalPrincipal(
                    subject_id=principal.user_id,
                    organization_id=principal.organization_id,
                    membership_id=principal.membership_id,
                ),
                correlation_id=correlation_id,
                deadline_at=deadline_at,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="forward evidence research is unavailable",
            ) from exc
        return ForwardEvidenceResearchResponse(result=result)

    return router


__all__ = ["ForwardEvidenceResearchResponse", "build_forward_evidence_router"]
