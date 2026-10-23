"""Minimal fake service for backend HTTP contract tests."""

from collections.abc import Mapping
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src.shared.internal_services import (
    INTERNAL_CONTRACT_VERSION,
    InternalAuthenticationError,
    InternalContextValidationError,
    InternalReadiness,
    ReadinessStatus,
    authenticate_internal_request,
)


class _FakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: dict[str, object]
    input: dict[str, object]


class _FakeResponse(BaseModel):
    correlation_id: str = Field(min_length=1)
    contract_version: Literal[INTERNAL_CONTRACT_VERSION]
    result: dict[str, object]


def create_fake_internal_service(
    *,
    expected_token: str,
    readiness_status: ReadinessStatus = ReadinessStatus.READY,
) -> FastAPI:
    """Build an in-process service with no dependency on backend app modules."""

    app = FastAPI()

    @app.get("/readyz", response_model=InternalReadiness)
    async def ready(response: Response) -> InternalReadiness:
        if readiness_status is ReadinessStatus.NOT_READY:
            response.status_code = 503
        return InternalReadiness(
            status=readiness_status,
            contract_version=INTERNAL_CONTRACT_VERSION,
        )

    @app.post("/v1/fake", response_model=_FakeResponse)
    async def execute(request: Request) -> _FakeResponse:
        try:
            body = _FakeRequest.model_validate(await request.json())
            context = authenticate_internal_request(
                request.headers.get("Authorization"),
                expected_token=expected_token,
                raw_context=body.context,
            )
        except InternalAuthenticationError as exc:
            raise HTTPException(status_code=401, detail=exc.code) from exc
        except InternalContextValidationError as exc:
            raise HTTPException(status_code=400, detail="invalid_context") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid_request") from exc

        result: Mapping[str, object] = {"echo": body.input}
        return _FakeResponse(
            correlation_id=context.correlation_id,
            contract_version=INTERNAL_CONTRACT_VERSION,
            result=dict(result),
        )

    return app
