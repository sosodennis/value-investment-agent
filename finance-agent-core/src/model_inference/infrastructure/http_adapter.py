from __future__ import annotations

from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.model_inference.domain.contracts import (
    FLSPrediction,
    FLSResult,
    FLSSentencesInput,
    InferenceOperation,
    InferenceRequest,
    InferenceResult,
    NewsSentimentInput,
    NewsSentimentResult,
)
from src.model_inference.domain.errors import InferenceErrorCode, InferenceFailure
from src.model_inference.infrastructure.settings import ModelInferenceSettings

_OPERATION_STATUS: dict[InferenceErrorCode, int] = {
    InferenceErrorCode.INVALID_ARGUMENT: 400,
    InferenceErrorCode.UNAUTHENTICATED: 401,
    InferenceErrorCode.MODEL_NOT_READY: 503,
    InferenceErrorCode.OVERLOADED: 429,
    InferenceErrorCode.DEADLINE_EXCEEDED: 504,
    InferenceErrorCode.CANCELLED: 499,
    InferenceErrorCode.UNAVAILABLE: 503,
    InferenceErrorCode.INFERENCE_FAILED: 500,
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _WireNewsResult(_StrictModel):
    label: Literal["positive", "negative", "neutral"]
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    scores: dict[str, float]

    @field_validator("scores")
    @classmethod
    def validate_scores(cls, scores: dict[str, float]) -> dict[str, float]:
        if any(not 0.0 <= score <= 1.0 for score in scores.values()):
            raise ValueError("sentiment scores must be probabilities")
        return scores


class _WireFLSPrediction(_StrictModel):
    keep: bool
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, allow_inf_nan=False)


class _WireFLSResult(_StrictModel):
    predictions: list[_WireFLSPrediction]


class _WireResponse(_StrictModel):
    schema_version: Literal["inference.v1"]
    request_id: str
    operation: Literal["news.sentiment", "sec.fls"]
    model_revision: str = Field(min_length=1)
    result: _WireNewsResult | _WireFLSResult


class _WireErrorBody(_StrictModel):
    code: str
    message: str
    retryable: bool
    retry_after_ms: int | None = Field(default=None, ge=0)


class _WireErrorResponse(_StrictModel):
    schema_version: Literal["inference.v1"]
    request_id: str
    error: _WireErrorBody


class HttpInferenceAdapter:
    def __init__(
        self,
        settings: ModelInferenceSettings,
        *,
        client: httpx.Client | None = None,
        async_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        headers = (
            {"Authorization": f"Bearer {settings.token}"} if settings.token else {}
        )
        limits = httpx.Limits(max_connections=16, max_keepalive_connections=8)
        self._client = client or httpx.Client(headers=headers, limits=limits)
        self._async_client = async_client or httpx.AsyncClient(
            headers=headers,
            limits=limits,
        )
        self._owns_client = client is None
        self._owns_async_client = async_client is None

    def infer(self, request: InferenceRequest) -> InferenceResult:
        try:
            response = self._client.post(
                self._url(request.operation),
                json=self._wire_request(request),
                headers={"X-Request-ID": request.request_id},
                timeout=request.deadline_ms / 1_000,
            )
        except httpx.TimeoutException as exc:
            raise self._failure(
                request,
                InferenceErrorCode.DEADLINE_EXCEEDED,
                retryable=False,
                message="model inference deadline exceeded",
            ) from exc
        except (httpx.TransportError, ValueError) as exc:
            raise self._failure(
                request,
                InferenceErrorCode.UNAVAILABLE,
                retryable=True,
                message="model inference service is unavailable",
            ) from exc
        return self._decode_response(response, request)

    async def infer_async(self, request: InferenceRequest) -> InferenceResult:
        try:
            response = await self._async_client.post(
                self._url(request.operation),
                json=self._wire_request(request),
                headers={"X-Request-ID": request.request_id},
                timeout=request.deadline_ms / 1_000,
            )
        except httpx.TimeoutException as exc:
            raise self._failure(
                request,
                InferenceErrorCode.DEADLINE_EXCEEDED,
                retryable=False,
                message="model inference deadline exceeded",
            ) from exc
        except (httpx.TransportError, ValueError) as exc:
            raise self._failure(
                request,
                InferenceErrorCode.UNAVAILABLE,
                retryable=True,
                message="model inference service is unavailable",
            ) from exc
        return self._decode_response(response, request)

    def _decode_response(
        self,
        response: httpx.Response,
        request: InferenceRequest,
    ) -> InferenceResult:
        try:
            if response.is_success:
                wire = _WireResponse.model_validate(response.json())
                if (
                    wire.request_id != request.request_id
                    or wire.operation != request.operation.value
                ):
                    raise ValueError("response correlation did not match request")
                if isinstance(request.input, NewsSentimentInput):
                    if not isinstance(wire.result, _WireNewsResult):
                        raise ValueError(
                            "news operation returned the wrong result type"
                        )
                    return NewsSentimentResult(
                        label=wire.result.label,
                        confidence=wire.result.confidence,
                        scores=wire.result.scores,
                        has_numbers=any(char.isdigit() for char in request.input.text),
                        model_revision=wire.model_revision,
                    )

                if not isinstance(wire.result, _WireFLSResult):
                    raise ValueError("FLS operation returned the wrong result type")
                if len(wire.result.predictions) != len(request.input.sentences):
                    raise ValueError("FLS result cardinality did not match request")
                return FLSResult(
                    predictions=tuple(
                        FLSPrediction(
                            keep=prediction.keep,
                            confidence=prediction.confidence,
                        )
                        for prediction in wire.result.predictions
                    ),
                    model_revision=wire.model_revision,
                )

            error_response = _WireErrorResponse.model_validate(response.json())
            if error_response.request_id != request.request_id:
                raise ValueError("error correlation did not match request")
            code = InferenceErrorCode(error_response.error.code)
            if _OPERATION_STATUS[code] != response.status_code:
                raise ValueError("error status did not match error code")
            raise InferenceFailure(
                code=code,
                request_id=request.request_id,
                retryable=error_response.error.retryable,
                retry_after_ms=error_response.error.retry_after_ms,
                message=f"model inference service returned {code.value}",
            )
        except InferenceFailure:
            raise
        except (ValidationError, ValueError, TypeError) as exc:
            raise self._failure(
                request,
                InferenceErrorCode.INFERENCE_FAILED,
                retryable=False,
                message="model inference service returned an invalid response",
            ) from exc

    def _wire_request(self, request: InferenceRequest) -> dict[str, object]:
        if isinstance(request.input, NewsSentimentInput):
            payload: dict[str, object] = {"text": request.input.text}
        elif isinstance(request.input, FLSSentencesInput):
            payload = {"sentences": list(request.input.sentences)}
        else:
            raise self._failure(
                request,
                InferenceErrorCode.INVALID_ARGUMENT,
                retryable=False,
                message="unsupported model inference input",
            )
        return {
            "schema_version": "inference.v1",
            "operation": request.operation.value,
            "deadline_ms": request.deadline_ms,
            "input": payload,
        }

    def _url(self, operation: InferenceOperation) -> str:
        base_url = (
            self._settings.news_url
            if operation is InferenceOperation.NEWS_SENTIMENT
            else self._settings.fls_url
        )
        return f"{base_url}/v1/inference"

    @staticmethod
    def _failure(
        request: InferenceRequest,
        code: InferenceErrorCode,
        *,
        retryable: bool,
        message: str,
    ) -> InferenceFailure:
        return InferenceFailure(
            code=code,
            request_id=request.request_id,
            retryable=retryable,
            message=message,
        )

    async def aclose(self) -> None:
        if self._owns_async_client:
            await self._async_client.aclose()
        if self._owns_client:
            self._client.close()
