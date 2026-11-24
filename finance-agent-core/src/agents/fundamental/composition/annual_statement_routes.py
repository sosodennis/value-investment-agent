"""HTTP composition for the authenticated, thread-owned statement reader."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request

from src.agents.fundamental.application.annual_statement_reader import (
    AnnualStatementReaderService,
)
from src.agents.fundamental.application.annual_statement_reader_contracts import (
    AnnualStatementArtifactResponse,
    AnnualStatementCatalogResponse,
    AnnualStatementReadErrorResponse,
    AnnualStatementReadFailure,
    AnnualStatementReadIntent,
)
from src.agents.fundamental.application.fundamental_service_port import (
    FundamentalServiceFailure,
)
from src.auth.entrypoint import (
    Principal,
    require_current_user,
    require_current_user_mutation,
)
from src.shared.internal_services import InternalPrincipal


def build_annual_statement_router(
    factory: Callable[[], AbstractAsyncContextManager[AnnualStatementReaderService]],
) -> APIRouter:
    router = APIRouter(
        prefix="/api/v1/fundamental/annual-statements", tags=["Annual statements"]
    )

    @router.get("/catalog", response_model=AnnualStatementCatalogResponse)
    async def catalog(
        principal: Principal = Depends(require_current_user),
    ) -> AnnualStatementCatalogResponse:
        async with factory() as service:
            return service.catalog()

    @router.post(
        "/read",
        response_model=AnnualStatementArtifactResponse,
        responses={
            code: {"model": AnnualStatementReadErrorResponse}
            for code in (404, 408, 429, 502, 503)
        },
    )
    async def read(
        body: AnnualStatementReadIntent,
        request: Request,
        principal: Principal = Depends(require_current_user_mutation),
    ) -> AnnualStatementArtifactResponse:
        supplied_org = request.headers.get("X-Organization-ID")
        if supplied_org is not None and supplied_org != principal.organization_id:
            raise HTTPException(status_code=403, detail="organization_context_mismatch")
        try:
            async with factory() as service:
                return await service.read(
                    body,
                    principal=InternalPrincipal(
                        subject_id=principal.user_id,
                        organization_id=principal.organization_id,
                        membership_id=principal.membership_id,
                    ),
                    correlation_id=request.headers.get("X-Request-ID") or str(uuid4()),
                    deadline_at=datetime.now(UTC) + timedelta(seconds=30),
                )
        except FundamentalServiceFailure as error:
            raise HTTPException(
                status_code=error.status_code
                if error.status_code in {404, 408, 429, 503}
                else 502,
                detail=AnnualStatementReadFailure(
                    code=error.code,
                    message="Annual statements could not be read.",
                    retryable=error.retryable,
                ).model_dump(mode="json"),
            ) from error

    return router
