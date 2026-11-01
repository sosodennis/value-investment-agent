from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from src.auth.entrypoint import Principal, get_ownership_service, require_current_user
from src.interface.artifacts.artifact_api_models import (
    ArtifactApiResponse,
    validate_artifact_api_response,
)
from src.services.artifact_manager import artifact_manager

router = APIRouter(prefix="/api/v1/artifacts", tags=["Artifacts"])


@router.get("/{artifact_id}", response_model=ArtifactApiResponse)
async def get_artifact(
    artifact_id: str,
    principal: Principal = Depends(require_current_user),
    run_id: str | None = Query(default=None, min_length=1),
) -> JSONResponse:
    thread_id = await artifact_manager.get_artifact_thread_id(artifact_id)
    referenced_thread_id = None
    if thread_id is None and run_id is not None:
        thread_id = await artifact_manager.get_agent_output_thread_id(
            artifact_id=artifact_id, run_id=run_id
        )
        if thread_id is None:
            referenced_thread_id = (
                await artifact_manager.get_referenced_artifact_thread_id(
                    artifact_id=artifact_id,
                    run_id=run_id,
                )
            )
            thread_id = referenced_thread_id
    elif run_id is not None:
        referenced_thread_id = await artifact_manager.get_referenced_artifact_thread_id(
            artifact_id=artifact_id,
            run_id=run_id,
        )
    if thread_id is None:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    if not await artifact_manager.belongs_to_organization(
        thread_id=thread_id,
        organization_id=principal.organization_id,
        run_id=run_id,
    ):
        raise HTTPException(status_code=404, detail="artifact_not_found")
    owned = await get_ownership_service().owns(
        user_id=principal.user_id,
        resource_type="thread",
        resource_id=thread_id,
    )
    if not owned:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    is_output_reference = await artifact_manager.is_agent_output_reference_any_thread(
        artifact_id=artifact_id
    )
    is_referenced_reference = False
    if run_id is None:
        is_referenced_reference = (
            await artifact_manager.is_referenced_artifact_reference(
                artifact_id=artifact_id,
                thread_id=thread_id,
            )
        )
    if (is_output_reference or is_referenced_reference) and run_id is None:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    if run_id is not None:
        direct_reference = await artifact_manager.is_agent_output_for_run(
            artifact_id=artifact_id, thread_id=thread_id, run_id=run_id
        )
        referenced_reference = referenced_thread_id == thread_id
        if not direct_reference and not referenced_reference:
            referenced_reference = (
                await artifact_manager.is_referenced_artifact_for_run(
                    artifact_id=artifact_id,
                    thread_id=thread_id,
                    run_id=run_id,
                )
            )
        if not direct_reference and not referenced_reference:
            raise HTTPException(status_code=404, detail="artifact_not_found")
    envelope = await artifact_manager.get_artifact_envelope(artifact_id)
    if envelope is None:
        raise HTTPException(status_code=404, detail="artifact_not_found")
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
