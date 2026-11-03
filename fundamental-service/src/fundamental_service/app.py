"""HTTP boundary for the contract foundation.

The calculation handlers remain intentionally unavailable until their owning slices
are integrated; the boundary and health contracts are stable from the first slice.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .contracts import SourceSnapshotV1, StatusResponseV1
from .snapshots import SnapshotError, SnapshotRepository


def create_app(snapshot_repository: SnapshotRepository | None = None) -> FastAPI:
    app = FastAPI(title="Fundamental service", version="0.1.0")

    @app.get("/livez", response_model=StatusResponseV1)
    async def livez() -> StatusResponseV1:
        return StatusResponseV1(contract_version="internal.v1", status="ok")

    @app.get("/readyz", response_model=StatusResponseV1)
    async def readyz() -> StatusResponseV1:
        return StatusResponseV1(contract_version="internal.v1", status="ok")

    @app.get("/v1/data/snapshots/{snapshot_id}", response_model=SourceSnapshotV1)
    async def get_snapshot(snapshot_id: str) -> SourceSnapshotV1:
        if snapshot_repository is None:
            raise HTTPException(
                status_code=503, detail="snapshot repository unavailable"
            )
        try:
            return snapshot_repository.get(snapshot_id)
        except SnapshotError as error:
            status_code = 404 if error.code == "SNAPSHOT_NOT_FOUND" else 503
            raise HTTPException(
                status_code=status_code,
                detail={"code": error.code, "message": error.message},
            ) from error

    return app


app = create_app()
