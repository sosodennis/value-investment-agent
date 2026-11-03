"""HTTP boundary for the contract foundation.

The calculation handlers remain intentionally unavailable until their owning slices
are integrated; the boundary and health contracts are stable from the first slice.
"""

from __future__ import annotations

from fastapi import FastAPI

from .contracts import StatusResponseV1


def create_app() -> FastAPI:
    app = FastAPI(title="Fundamental service", version="0.1.0")

    @app.get("/livez", response_model=StatusResponseV1)
    async def livez() -> StatusResponseV1:
        return StatusResponseV1(contract_version="internal.v1", status="ok")

    @app.get("/readyz", response_model=StatusResponseV1)
    async def readyz() -> StatusResponseV1:
        return StatusResponseV1(contract_version="internal.v1", status="ok")

    return app


app = create_app()
