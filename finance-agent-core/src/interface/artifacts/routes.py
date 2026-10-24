from fastapi import APIRouter, Depends, HTTPException
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
) -> JSONResponse:
    artifact = await artifact_manager.get_artifact(artifact_id)
    if artifact is None or artifact.thread_id is None:
        raise HTTPException(status_code=404, detail="artifact_not_found")
    owned = await get_ownership_service().owns(
        user_id=principal.user_id,
        resource_type="thread",
        resource_id=artifact.thread_id,
    )
    if not owned:
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
