"""HTTP boundary for the contract foundation.

The calculation handlers remain intentionally unavailable until their owning slices
are integrated; the boundary and health contracts are stable from the first slice.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request

from .contracts import (
    CalculationArtifactV1,
    SourceSnapshotV1,
    StatusResponseV1,
    ValidationResponseV1,
    ValuationInputV1,
)
from .calculator import CalculationRefusal, calculate, validate
from .snapshots import SnapshotError, SnapshotRepository
from .uncertainty import (
    MonteCarloRequestV1,
    ScenarioV1,
    SensitivityRequestV1,
    UncertaintyReportV1,
    run_uncertainty,
)


class UncertaintyRequestV1(ValuationInputV1):
    """HTTP input carrying explicit uncertainty controls alongside valuation input."""

    scenarios: tuple[ScenarioV1, ...] = ()
    sensitivity: tuple[SensitivityRequestV1, ...] = ()
    monte_carlo: MonteCarloRequestV1 | None = None


def create_app(snapshot_repository: SnapshotRepository | None = None) -> FastAPI:
    app = FastAPI(title="Fundamental service", version="0.1.0")

    @app.get("/livez", response_model=StatusResponseV1)
    async def livez() -> StatusResponseV1:
        return StatusResponseV1(contract_version="internal.v1", status="ok")

    @app.get("/readyz", response_model=StatusResponseV1)
    async def readyz() -> StatusResponseV1:
        return StatusResponseV1(
            contract_version="internal.v1",
            status="ok" if snapshot_repository is not None else "not_ready",
        )

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

    @app.post("/v1/valuation/validate", response_model=ValidationResponseV1)
    async def validate_valuation(request: Request) -> ValidationResponseV1:
        request = ValuationInputV1.model_validate_json(await request.body())
        resolved = validate(request)
        return ValidationResponseV1(
            contract_version="fundamental.v1",
            input=resolved,
            input_digest=resolved.input_digest,
            quality_status=resolved.quality.status,
            issue_codes=resolved.quality.issue_codes,
            missing_evidence=resolved.quality.missing_evidence,
        )

    @app.post("/v1/valuation/calculate", response_model=CalculationArtifactV1)
    async def calculate_valuation(request: Request) -> CalculationArtifactV1:
        try:
            request = ValuationInputV1.model_validate_json(await request.body())
            return calculate(request)
        except CalculationRefusal as error:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": error.code,
                    "message": str(error),
                    "correlation_id": "http",
                    "retryable": False,
                },
            ) from error

    @app.post("/v1/valuation/uncertainty", response_model=UncertaintyReportV1)
    async def uncertainty_valuation(request: Request) -> UncertaintyReportV1:
        try:
            request = UncertaintyRequestV1.model_validate_json(await request.body())
            return run_uncertainty(
                request,
                monte_carlo=request.monte_carlo,
                scenarios=request.scenarios,
                sensitivity=request.sensitivity,
            )
        except (CalculationRefusal, ValueError) as error:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": getattr(error, "code", "UNCERTAINTY_INVALID"),
                    "message": str(error),
                    "correlation_id": "http",
                    "retryable": False,
                },
            ) from error

    return app


app = create_app()
