from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.agents.fundamental.application.wiring import (
    build_default_forward_evidence_research_service,
)
from src.agents.fundamental.capabilities.forward_evidence.contracts import (
    ForwardEvidenceResearchRequest,
)
from src.agents.fundamental.capabilities.forward_evidence.research_service import (
    ForwardEvidenceResearchService,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalForwardEvidenceReviewResultV1,
)
from src.auth.entrypoint import Principal, require_current_user_mutation
from src.shared.internal_services import InternalPrincipal

router = APIRouter(
    prefix="/api/v1/fundamental/forward-evidence",
    tags=["Fundamental forward evidence"],
)


class ForwardEvidenceResearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: FundamentalForwardEvidenceReviewResultV1


@router.post("/research", response_model=ForwardEvidenceResearchResponse)
async def research_forward_evidence(
    body: ForwardEvidenceResearchRequest,
    request: Request,
    principal: Principal = Depends(require_current_user_mutation),
) -> ForwardEvidenceResearchResponse:
    service: ForwardEvidenceResearchService = (
        build_default_forward_evidence_research_service()
    )
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


__all__ = ["ForwardEvidenceResearchResponse", "router"]
