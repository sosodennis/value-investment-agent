from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from src.artifacts.application.ports import ArtifactCurrentReadFailure
from src.artifacts.application.service import ArtifactService
from src.artifacts.application.wiring import (
    build_default_artifact_service,
    build_default_fiscal_artifact_current_reader,
)
from src.artifacts.interface.api_models import (
    ArtifactApiResponse,
    validate_artifact_api_response,
)
from src.auth.entrypoint import Principal, get_ownership_service, require_current_user
from src.shared.artifacts.artifact_data_models import FinancialReportsArtifactData
from src.shared.artifacts.statement_read_artifact import FiscalSavedReadV3
from src.shared.internal_services import InternalPrincipal

router = APIRouter(prefix="/api/v1/artifacts", tags=["Artifacts"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="artifact_not_found")


@router.get("/{artifact_id}", response_model=ArtifactApiResponse)
async def get_artifact(
    artifact_id: str,
    request: Request,
    principal: Principal = Depends(require_current_user),
    run_id: str | None = Query(default=None, min_length=1),
    expected_thread_id: str | None = Query(
        default=None, min_length=1, alias="thread_id"
    ),
    artifacts: ArtifactService = Depends(build_default_artifact_service),
) -> JSONResponse:
    if run_id is not None:
        thread_id = await artifacts.get_run_thread_id(
            run_id=run_id,
            organization_id=principal.organization_id,
        )
        if thread_id is None or (
            expected_thread_id is not None and expected_thread_id != thread_id
        ):
            raise _not_found()
        if not await get_ownership_service().owns(
            user_id=principal.user_id,
            resource_type="thread",
            resource_id=thread_id,
        ):
            raise _not_found()
        artifact_thread_id = await artifacts.get_artifact_thread_id(artifact_id)
        if artifact_thread_id is not None and artifact_thread_id != thread_id:
            raise _not_found()

        direct_reference = await artifacts.is_agent_output_for_run(
            artifact_id=artifact_id,
            thread_id=thread_id,
            run_id=run_id,
        )
        child_reference = False
        if not direct_reference:
            child_reference = await artifacts.is_referenced_artifact_for_run(
                artifact_id=artifact_id,
                thread_id=thread_id,
                run_id=run_id,
            )
        if not direct_reference and not child_reference:
            raise _not_found()
    else:
        thread_id = await artifacts.get_artifact_thread_id(artifact_id)
        if thread_id is None or (
            expected_thread_id is not None and expected_thread_id != thread_id
        ):
            raise _not_found()
        if not await artifacts.belongs_to_organization(
            thread_id=thread_id,
            organization_id=principal.organization_id,
        ):
            raise _not_found()
        if not await get_ownership_service().owns(
            user_id=principal.user_id,
            resource_type="thread",
            resource_id=thread_id,
        ):
            raise _not_found()
        if await artifacts.is_agent_output_reference(
            artifact_id=artifact_id,
            thread_id=thread_id,
        ) or await artifacts.is_referenced_artifact_reference(
            artifact_id=artifact_id,
            thread_id=thread_id,
        ):
            raise _not_found()

    envelope = await artifacts.get_artifact_envelope(artifact_id)
    if envelope is None:
        raise _not_found()
    validated = validate_artifact_api_response(
        envelope.model_dump(mode="json"), context=f"artifact {artifact_id}"
    )
    if envelope.kind == "financial_reports":
        data = FinancialReportsArtifactData.model_validate(envelope.data)
        if data.statement_read is not None and isinstance(
            data.statement_read.read, FiscalSavedReadV3
        ):
            try:
                async with build_default_fiscal_artifact_current_reader() as reader:
                    await reader.check_current(
                        data.statement_read.read,
                        principal=InternalPrincipal(
                            subject_id=principal.user_id,
                            organization_id=principal.organization_id,
                            membership_id=principal.membership_id,
                        ),
                        correlation_id=request.headers.get("X-Request-ID")
                        or str(uuid4()),
                        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
                    )
            except ArtifactCurrentReadFailure as error:
                raise HTTPException(
                    status_code=error.status_code,
                    detail={
                        "code": error.code,
                        "message": "Saved fiscal statements could not be read.",
                        "retryable": error.retryable,
                    },
                    headers={"Cache-Control": "private, no-store"},
                ) from error
            return JSONResponse(
                content=validated.model_dump(mode="json"),
                headers={"Cache-Control": "private, no-store"},
            )
    return JSONResponse(
        content=validated.model_dump(mode="json"),
        headers={
            "Cache-Control": "private, max-age=3600",
            "ETag": f'"{artifact_id}"',
        },
    )
