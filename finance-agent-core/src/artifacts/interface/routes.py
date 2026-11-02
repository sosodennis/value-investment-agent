from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from src.artifacts.application.service import ArtifactService
from src.artifacts.application.wiring import build_default_artifact_service
from src.artifacts.interface.api_models import (
    ArtifactApiResponse,
    validate_artifact_api_response,
)
from src.auth.entrypoint import Principal, get_ownership_service, require_current_user

router = APIRouter(prefix="/api/v1/artifacts", tags=["Artifacts"])


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="artifact_not_found")


@router.get("/{artifact_id}", response_model=ArtifactApiResponse)
async def get_artifact(
    artifact_id: str,
    principal: Principal = Depends(require_current_user),
    run_id: str | None = Query(default=None, min_length=1),
    artifacts: ArtifactService = Depends(build_default_artifact_service),
) -> JSONResponse:
    if run_id is not None:
        thread_id = await artifacts.get_run_thread_id(
            run_id=run_id,
            organization_id=principal.organization_id,
        )
        if thread_id is None:
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
        if thread_id is None:
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
    return JSONResponse(
        content=validated.model_dump(mode="json"),
        headers={
            "Cache-Control": "private, max-age=3600",
            "ETag": f'"{artifact_id}"',
        },
    )
