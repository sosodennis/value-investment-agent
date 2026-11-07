"""HTTP adapter for the independently deployed Fundamental service.

The adapter owns transport concerns only.  It sends the shared signed context
and a service-owned ``fundamental.v1`` input, then returns the narrow envelope
projection owned by the agent.  It never imports the Fundamental service
implementation or retries through a local calculator.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

import httpx
from pydantic import ValidationError

from src.agents.fundamental.application.fundamental_service_port import (
    FUNDAMENTAL_SERVICE_WORKFLOW_TIMEOUT_SECONDS,
    FundamentalOperation,
    FundamentalServiceFailure,
)
from src.agents.fundamental.interface.fundamental_service_contracts import (
    FundamentalFactsReadResultV1,
    FundamentalIdentityResolutionRequestV1,
    FundamentalIdentityResolutionV1,
    FundamentalServiceErrorV1,
    FundamentalServiceResponseV1,
)
from src.shared.internal_services import (
    InternalPrincipal,
    build_internal_context,
)

_DEFAULT_URL: Final[str] = "http://fundamental-service:8080"
_DEFAULT_TIMEOUT_SECONDS: Final[float] = 10.0
_DEFAULT_INGESTION_TIMEOUT_SECONDS: Final[float] = (
    FUNDAMENTAL_SERVICE_WORKFLOW_TIMEOUT_SECONDS
)
_DEFAULT_MAX_ATTEMPTS: Final[int] = 2
_OPERATION_PATHS: dict[FundamentalOperation, str] = {
    "ingest_sec_data": "/v1/data/ingestions",
    "resolve_identity": "/v1/identity/resolve",
    "resolve_snapshot": "/v1/data/snapshots/resolve",
    "read_facts": "/v1/data/facts",
    "validate": "/v1/valuation/validate",
    "validate_with_policy": "/v1/valuation/validate-with-policy",
    "calculate": "/v1/valuation/calculate",
    "uncertainty": "/v1/valuation/uncertainty",
    "replay": "/v1/valuation/replay",
}
_OPERATION_METHODS: dict[FundamentalOperation, str] = {
    "read_facts": "GET",
}


@dataclass(frozen=True)
class FundamentalServiceClientSettings:
    """Environment-backed workload credentials and transport limits."""

    base_url: str
    service_token: str
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    ingestion_timeout_seconds: float = _DEFAULT_INGESTION_TIMEOUT_SECONDS
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS

    @classmethod
    def from_env(cls) -> FundamentalServiceClientSettings:
        raw_timeout = os.getenv("FUNDAMENTAL_SERVICE_TIMEOUT_SECONDS")
        timeout_seconds = (
            float(raw_timeout) if raw_timeout is not None else _DEFAULT_TIMEOUT_SECONDS
        )
        raw_attempts = os.getenv("FUNDAMENTAL_SERVICE_MAX_ATTEMPTS")
        max_attempts = (
            int(raw_attempts) if raw_attempts is not None else _DEFAULT_MAX_ATTEMPTS
        )
        raw_ingestion_timeout = os.getenv(
            "FUNDAMENTAL_SERVICE_INGESTION_TIMEOUT_SECONDS"
        )
        ingestion_timeout_seconds = (
            float(raw_ingestion_timeout)
            if raw_ingestion_timeout is not None
            else _DEFAULT_INGESTION_TIMEOUT_SECONDS
        )
        if timeout_seconds <= 0:
            raise ValueError("FUNDAMENTAL_SERVICE_TIMEOUT_SECONDS must be positive")
        if ingestion_timeout_seconds <= 0:
            raise ValueError(
                "FUNDAMENTAL_SERVICE_INGESTION_TIMEOUT_SECONDS must be positive"
            )
        if max_attempts < 1 or max_attempts > 3:
            raise ValueError("FUNDAMENTAL_SERVICE_MAX_ATTEMPTS must be between 1 and 3")
        return cls(
            base_url=os.getenv("FUNDAMENTAL_SERVICE_URL", _DEFAULT_URL).rstrip("/"),
            service_token=os.getenv("FUNDAMENTAL_SERVICE_TOKEN", "").strip(),
            timeout_seconds=timeout_seconds,
            ingestion_timeout_seconds=ingestion_timeout_seconds,
            max_attempts=max_attempts,
        )

    def validate(self) -> None:
        if not self.base_url:
            raise ValueError("FUNDAMENTAL_SERVICE_URL is required")
        if not self.service_token:
            raise ValueError("FUNDAMENTAL_SERVICE_TOKEN is required")
        if self.ingestion_timeout_seconds <= 0:
            raise ValueError(
                "FUNDAMENTAL_SERVICE_INGESTION_TIMEOUT_SECONDS must be positive"
            )


class HttpFundamentalServiceClient:
    """Typed asynchronous client for the Fundamental service boundary."""

    def __init__(
        self,
        settings: FundamentalServiceClientSettings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or FundamentalServiceClientSettings.from_env()
        self._client = client or httpx.AsyncClient(timeout=None)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def execute(
        self,
        operation: FundamentalOperation,
        input_payload: Mapping[str, object],
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalServiceResponseV1:
        try:
            self._settings.validate()
        except ValueError as exc:
            raise FundamentalServiceFailure(
                "SERVICE_NOT_CONFIGURED",
                str(exc),
                retryable=False,
            ) from exc
        path = _OPERATION_PATHS.get(operation)
        if path is None:  # pragma: no cover - protected by the Literal port
            raise FundamentalServiceFailure(
                "invalid_operation",
                f"unsupported Fundamental operation: {operation}",
                retryable=False,
            )
        if deadline_at.tzinfo is None or deadline_at.utcoffset() is None:
            raise FundamentalServiceFailure(
                "invalid_deadline",
                "Fundamental service deadline must be timezone-aware",
                retryable=False,
            )

        context = build_internal_context(
            principal=principal,
            correlation_id=correlation_id,
            deadline_at=deadline_at.astimezone(UTC),
            audience="fundamental-service",
            signing_key=self._settings.service_token,
        )
        payload = {
            "context": context.model_dump(mode="json"),
            "input": dict(input_payload),
        }
        headers = {
            "Authorization": f"Bearer {self._settings.service_token}",
            "X-Request-ID": correlation_id,
        }
        if principal.organization_id:
            headers["X-Organization-ID"] = principal.organization_id
        operation_timeout = (
            self._settings.ingestion_timeout_seconds
            if operation in {"ingest_sec_data", "resolve_identity"}
            else self._settings.timeout_seconds
        )

        last_failure: FundamentalServiceFailure | None = None
        for attempt in range(1, self._settings.max_attempts + 1):
            remaining = (
                deadline_at.astimezone(UTC) - datetime.now(UTC)
            ).total_seconds()
            if remaining <= 0:
                raise FundamentalServiceFailure(
                    "DEADLINE_EXCEEDED",
                    "Fundamental service deadline expired before the request",
                    retryable=False,
                    status_code=408,
                )
            try:
                response = await self._client.request(
                    _OPERATION_METHODS.get(operation, "POST"),
                    f"{self._settings.base_url}{path}",
                    json=payload,
                    headers=headers,
                    timeout=min(remaining, operation_timeout),
                )
            except httpx.TimeoutException:
                last_failure = FundamentalServiceFailure(
                    "DEADLINE_EXCEEDED",
                    "Fundamental service request timed out",
                    retryable=attempt < self._settings.max_attempts,
                    status_code=504,
                )
            except httpx.TransportError:
                last_failure = FundamentalServiceFailure(
                    "UPSTREAM_UNAVAILABLE",
                    "Fundamental service is unavailable",
                    retryable=True,
                    status_code=503,
                )
            else:
                try:
                    if response.is_success:
                        envelope = FundamentalServiceResponseV1.model_validate(
                            response.json()
                        )
                        if envelope.correlation_id != correlation_id:
                            raise ValueError(
                                "Fundamental response correlation mismatch"
                            )
                        return envelope
                    error_envelope = FundamentalServiceErrorV1.model_validate(
                        response.json()
                    )
                    if error_envelope.correlation_id != correlation_id:
                        raise ValueError("Fundamental error correlation mismatch")
                    error = error_envelope.error
                    code = error.get("code")
                    message = error.get("message")
                    retryable = error.get("retryable")
                    retry_after_ms = error.get("retry_after_ms")
                    if not isinstance(code, str) or not code:
                        raise ValueError("Fundamental error code is invalid")
                    if not isinstance(message, str) or not message:
                        raise ValueError("Fundamental error message is invalid")
                    if not isinstance(retryable, bool):
                        raise ValueError("Fundamental error retryability is invalid")
                    last_failure = FundamentalServiceFailure(
                        code,
                        message,
                        retryable=retryable,
                        status_code=response.status_code,
                        retry_after_ms=(
                            retry_after_ms if isinstance(retry_after_ms, int) else None
                        ),
                    )
                except (ValidationError, ValueError, TypeError) as exc:
                    last_failure = FundamentalServiceFailure(
                        "UPSTREAM_MALFORMED",
                        "Fundamental service returned an invalid response",
                        retryable=False,
                        status_code=502,
                    )
                    if attempt >= self._settings.max_attempts:
                        raise last_failure from exc

            if last_failure is None:
                continue
            if not last_failure.retryable or attempt >= self._settings.max_attempts:
                raise last_failure
            remaining = (
                deadline_at.astimezone(UTC) - datetime.now(UTC)
            ).total_seconds()
            if remaining <= 0:
                raise FundamentalServiceFailure(
                    "DEADLINE_EXCEEDED",
                    "Fundamental service deadline expired during retry",
                    retryable=False,
                    status_code=408,
                ) from last_failure
            retry_delay = (
                last_failure.retry_after_ms / 1000
                if last_failure.retry_after_ms is not None
                else min(0.01, remaining / 10)
            )
            await asyncio.sleep(min(retry_delay, remaining))

        raise last_failure or FundamentalServiceFailure(
            "UPSTREAM_UNAVAILABLE",
            "Fundamental service request failed",
            retryable=False,
            status_code=503,
        )

    async def read_facts(
        self,
        input_payload: Mapping[str, object],
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalFactsReadResultV1:
        """Read and validate the immutable fact projection for one snapshot."""

        response = await self.execute(
            "read_facts",
            input_payload,
            principal=principal,
            correlation_id=correlation_id,
            deadline_at=deadline_at,
        )
        try:
            return FundamentalFactsReadResultV1.model_validate(response.result)
        except ValidationError as exc:
            raise FundamentalServiceFailure(
                "UPSTREAM_MALFORMED",
                "Fundamental service returned an invalid facts projection",
                retryable=False,
                status_code=502,
            ) from exc

    async def resolve_identity(
        self,
        request: FundamentalIdentityResolutionRequestV1,
        *,
        principal: InternalPrincipal,
        correlation_id: str,
        deadline_at: datetime,
    ) -> FundamentalIdentityResolutionV1:
        """Call the service resolver and validate its complete evidence digest."""
        response = await self.execute(
            "resolve_identity",
            request.model_dump(mode="json"),
            principal=principal,
            correlation_id=correlation_id,
            deadline_at=deadline_at,
        )
        try:
            return FundamentalIdentityResolutionV1.model_validate_json(
                json.dumps(response.result)
            )
        except (ValidationError, TypeError, ValueError) as error:
            raise FundamentalServiceFailure(
                "UPSTREAM_MALFORMED",
                "Fundamental service returned an invalid identity response",
                retryable=False,
                status_code=502,
            ) from error


__all__ = ["FundamentalServiceClientSettings", "HttpFundamentalServiceClient"]
