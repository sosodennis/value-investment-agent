from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from src.model_inference.application.context import get_inference_principal
from src.model_inference.application.ports import InferenceTransport
from src.model_inference.application.sync_runner import BoundedSyncRunner
from src.model_inference.domain.contracts import (
    OPERATION_POLICIES,
    FLSPrediction,
    FLSResult,
    FLSSentencesInput,
    InferenceOperation,
    InferenceRequest,
    InferenceResult,
    ModelInference,
    NewsSentimentInput,
    NewsSentimentResult,
)
from src.model_inference.domain.errors import InferenceErrorCode, InferenceFailure

_MAX_ATTEMPTS = 2
_MAX_RETRY_AFTER_MS = 500
_DEFAULT_RETRY_DELAY_MS = 50
_FLS_REQUEST_SENTENCE_LIMIT = 120
_FLS_MODEL_BATCH_SIZE = 32
_DEADLINE_MARGIN_SECONDS = 0.001
_SYNC_MAX_WORKERS = 16


class ModelInferenceService(ModelInference):
    def __init__(
        self,
        transport: InferenceTransport,
        *,
        sync_runner: BoundedSyncRunner | None = None,
    ) -> None:
        self._transport = transport
        self._sync_runner = sync_runner or BoundedSyncRunner(
            max_workers=_SYNC_MAX_WORKERS
        )

    async def news_sentiment(self, text: str) -> NewsSentimentResult:
        request_id = uuid4().hex
        principal_subject_id = self._principal_subject_id(request_id)
        policy = OPERATION_POLICIES[InferenceOperation.NEWS_SENTIMENT]
        if not text.strip() or len(text) > int(policy.max_text_chars or 0):
            raise InferenceFailure(
                code=InferenceErrorCode.INVALID_ARGUMENT,
                request_id=request_id,
                retryable=False,
                message="news text is outside the allowed input limits",
            )
        deadline = time.monotonic() + policy.default_deadline_ms / 1_000
        deadline_at = datetime.now(timezone.utc) + timedelta(
            milliseconds=policy.default_deadline_ms
        )
        result = await self._infer_async(
            operation=InferenceOperation.NEWS_SENTIMENT,
            payload=NewsSentimentInput(text=text),
            request_id=request_id,
            deadline=deadline,
            principal_subject_id=principal_subject_id,
            deadline_at=deadline_at,
        )
        if not isinstance(result, NewsSentimentResult):
            raise self._protocol_failure(request_id)
        return result

    def news_sentiment_sync(self, text: str) -> NewsSentimentResult:
        request_id = uuid4().hex
        principal_subject_id = self._principal_subject_id(request_id)
        policy = OPERATION_POLICIES[InferenceOperation.NEWS_SENTIMENT]
        if not text.strip() or len(text) > int(policy.max_text_chars or 0):
            raise InferenceFailure(
                code=InferenceErrorCode.INVALID_ARGUMENT,
                request_id=request_id,
                retryable=False,
                message="news text is outside the allowed input limits",
            )
        deadline = time.monotonic() + policy.default_deadline_ms / 1_000
        deadline_at = datetime.now(timezone.utc) + timedelta(
            milliseconds=policy.default_deadline_ms
        )
        return self._sync_runner.run(
            request_id=request_id,
            deadline=deadline,
            work=lambda: self._news_sentiment_sync_work(
                text=text,
                request_id=request_id,
                deadline=deadline,
                principal_subject_id=principal_subject_id,
                deadline_at=deadline_at,
            ),
        )

    def fls_predictions(self, sentences: Sequence[str]) -> FLSResult:
        request_id = uuid4().hex
        principal_subject_id = self._principal_subject_id(request_id)
        policy = OPERATION_POLICIES[InferenceOperation.SEC_FLS]
        if not sentences:
            raise InferenceFailure(
                code=InferenceErrorCode.INVALID_ARGUMENT,
                request_id=request_id,
                retryable=False,
                message="FLS requires at least one sentence",
            )
        if any(not sentence.strip() for sentence in sentences) or any(
            len(sentence) > int(policy.max_sentence_chars or 0)
            for sentence in sentences
        ):
            raise InferenceFailure(
                code=InferenceErrorCode.INVALID_ARGUMENT,
                request_id=request_id,
                retryable=False,
                message="FLS sentence is outside the allowed input limits",
            )

        sentence_values = tuple(sentences)
        deadline = time.monotonic() + policy.default_deadline_ms / 1_000
        deadline_at = datetime.now(timezone.utc) + timedelta(
            milliseconds=policy.default_deadline_ms
        )
        return self._sync_runner.run(
            request_id=request_id,
            deadline=deadline,
            work=lambda: self._fls_predictions_sync_work(
                sentences=sentence_values,
                request_id=request_id,
                deadline=deadline,
                principal_subject_id=principal_subject_id,
                deadline_at=deadline_at,
            ),
        )

    def _news_sentiment_sync_work(
        self,
        *,
        text: str,
        request_id: str,
        deadline: float,
        principal_subject_id: str,
        deadline_at: datetime,
    ) -> NewsSentimentResult:
        result = self._infer_sync(
            operation=InferenceOperation.NEWS_SENTIMENT,
            payload=NewsSentimentInput(text=text),
            request_id=request_id,
            deadline=deadline,
            retries_used=0,
            principal_subject_id=principal_subject_id,
            deadline_at=deadline_at,
        )
        if not isinstance(result, NewsSentimentResult):
            raise self._protocol_failure(request_id)
        return result

    def _fls_predictions_sync_work(
        self,
        *,
        sentences: tuple[str, ...],
        request_id: str,
        deadline: float,
        principal_subject_id: str,
        deadline_at: datetime,
    ) -> FLSResult:
        predictions: list[FLSPrediction] = []
        model_revision: str | None = None
        retries_used = 0
        for chunk_index, start in enumerate(
            range(0, len(sentences), _FLS_REQUEST_SENTENCE_LIMIT)
        ):
            chunk = tuple(sentences[start : start + _FLS_REQUEST_SENTENCE_LIMIT])
            chunk_request_id = f"{request_id}:{chunk_index}"
            result, retries_used = self._infer_sync_with_retry_count(
                operation=InferenceOperation.SEC_FLS,
                payload=FLSSentencesInput(sentences=chunk),
                request_id=chunk_request_id,
                deadline=deadline,
                retries_used=retries_used,
                principal_subject_id=principal_subject_id,
                deadline_at=deadline_at,
            )
            if not isinstance(result, FLSResult):
                raise self._protocol_failure(chunk_request_id)
            if len(result.predictions) != len(chunk):
                raise self._protocol_failure(chunk_request_id)
            if model_revision is not None and model_revision != result.model_revision:
                raise self._protocol_failure(chunk_request_id)
            model_revision = result.model_revision
            predictions.extend(result.predictions)

        if model_revision is None:
            raise self._protocol_failure(request_id)
        return FLSResult(predictions=tuple(predictions), model_revision=model_revision)

    async def _infer_async(
        self,
        *,
        operation: InferenceOperation,
        payload: NewsSentimentInput | FLSSentencesInput,
        request_id: str,
        deadline: float,
        principal_subject_id: str,
        deadline_at: datetime,
    ) -> InferenceResult:
        policy = OPERATION_POLICIES[operation]
        for attempt in range(_MAX_ATTEMPTS):
            deadline_ms = self._remaining_ms(deadline, request_id)
            request = InferenceRequest(
                operation=operation,
                input=payload,
                request_id=request_id,
                deadline_ms=min(deadline_ms, policy.maximum_deadline_ms),
                principal_subject_id=principal_subject_id,
                deadline_at=deadline_at,
            )
            try:
                result = await asyncio.wait_for(
                    self._transport.infer_async(request),
                    timeout=deadline_ms / 1_000,
                )
                if time.monotonic() >= deadline:
                    raise self._deadline_failure(request_id)
                return result
            except asyncio.CancelledError:
                raise
            except TimeoutError as exc:
                raise self._deadline_failure(request_id) from exc
            except InferenceFailure as exc:
                if time.monotonic() >= deadline:
                    raise self._deadline_failure(request_id) from exc
                delay_ms = self._retry_delay_ms(exc)
                if attempt + 1 >= _MAX_ATTEMPTS or delay_ms is None:
                    raise
                remaining_ms = (deadline - time.monotonic()) * 1_000
                if delay_ms + _DEADLINE_MARGIN_SECONDS * 1_000 >= remaining_ms:
                    raise
                await asyncio.sleep(delay_ms / 1_000)
        raise self._deadline_failure(request_id)

    def _infer_sync(
        self,
        *,
        operation: InferenceOperation,
        payload: NewsSentimentInput | FLSSentencesInput,
        request_id: str,
        deadline: float,
        retries_used: int,
        principal_subject_id: str,
        deadline_at: datetime,
    ) -> InferenceResult:
        result, _retries_used = self._infer_sync_with_retry_count(
            operation=operation,
            payload=payload,
            request_id=request_id,
            deadline=deadline,
            retries_used=retries_used,
            principal_subject_id=principal_subject_id,
            deadline_at=deadline_at,
        )
        return result

    def _infer_sync_with_retry_count(
        self,
        *,
        operation: InferenceOperation,
        payload: NewsSentimentInput | FLSSentencesInput,
        request_id: str,
        deadline: float,
        retries_used: int,
        principal_subject_id: str,
        deadline_at: datetime,
    ) -> tuple[InferenceResult, int]:
        policy = OPERATION_POLICIES[operation]
        attempt = 0
        while True:
            deadline_ms = self._remaining_ms(deadline, request_id)
            request = InferenceRequest(
                operation=operation,
                input=payload,
                request_id=request_id,
                deadline_ms=min(deadline_ms, policy.maximum_deadline_ms),
                principal_subject_id=principal_subject_id,
                deadline_at=deadline_at,
            )
            try:
                result = self._transport.infer(request)
                if time.monotonic() >= deadline:
                    raise self._deadline_failure(request_id)
                return result, retries_used
            except InferenceFailure as exc:
                if time.monotonic() >= deadline:
                    raise self._deadline_failure(request_id) from exc
                delay_ms = self._retry_delay_ms(exc)
                if attempt + 1 >= _MAX_ATTEMPTS or retries_used > 0 or delay_ms is None:
                    raise
                remaining_ms = (deadline - time.monotonic()) * 1_000
                if delay_ms + _DEADLINE_MARGIN_SECONDS * 1_000 >= remaining_ms:
                    raise
                time.sleep(delay_ms / 1_000)
                retries_used += 1
                attempt += 1

    @staticmethod
    def _principal_subject_id(request_id: str) -> str:
        principal = get_inference_principal()
        if principal is None:
            raise InferenceFailure(
                code=InferenceErrorCode.UNAUTHENTICATED,
                request_id=request_id,
                retryable=False,
                message="authenticated principal context is required",
            )
        return principal.subject_id

    @staticmethod
    def _remaining_ms(deadline: float, request_id: str) -> int:
        remaining_ms = math.ceil((deadline - time.monotonic()) * 1_000)
        if remaining_ms <= 0:
            raise ModelInferenceService._deadline_failure(request_id)
        return remaining_ms

    @staticmethod
    def _retry_delay_ms(failure: InferenceFailure) -> int | None:
        if not failure.retryable:
            return None
        if failure.code is InferenceErrorCode.DEADLINE_EXCEEDED:
            return None
        if failure.code is InferenceErrorCode.OVERLOADED:
            if failure.retry_after_ms is None or failure.retry_after_ms <= 0:
                return None
            return min(failure.retry_after_ms, _MAX_RETRY_AFTER_MS)
        if failure.code not in {
            InferenceErrorCode.MODEL_NOT_READY,
            InferenceErrorCode.UNAVAILABLE,
        }:
            return None
        if failure.retry_after_ms is None:
            return _DEFAULT_RETRY_DELAY_MS
        if failure.retry_after_ms <= 0:
            return None
        return min(failure.retry_after_ms, _MAX_RETRY_AFTER_MS)

    @staticmethod
    def _deadline_failure(request_id: str) -> InferenceFailure:
        return InferenceFailure(
            code=InferenceErrorCode.DEADLINE_EXCEEDED,
            request_id=request_id,
            retryable=False,
            message="model inference deadline exceeded",
        )

    @staticmethod
    def _protocol_failure(request_id: str) -> InferenceFailure:
        return InferenceFailure(
            code=InferenceErrorCode.INFERENCE_FAILED,
            request_id=request_id,
            retryable=False,
            message="model inference response did not match the domain contract",
        )

    async def aclose(self) -> None:
        self._sync_runner.close()
        await self._transport.aclose()
