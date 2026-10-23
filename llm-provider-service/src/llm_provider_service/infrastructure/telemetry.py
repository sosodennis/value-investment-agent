"""Bounded, provider-neutral telemetry for the LLM gateway."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from logging import getLogger as get_logger
from time import perf_counter

from src.llm_provider_service.domain.contracts import (
    CompletionRequest,
    CompletionResult,
    LLMAttribution,
    LLMProviderError,
)


def log_event(logger, *, event, message, level, error_code=None, fields=None):
    logger.log(
        level,
        "%s: %s",
        event,
        message,
        extra={"error_code": error_code, **(fields or {})},
    )


_logger = get_logger(__name__)


@dataclass(frozen=True)
class LLMProviderTelemetrySnapshot:
    requests: int
    successes: int
    failures: int
    attempts: int
    retries: int
    streams: int
    stream_interruptions: int
    total_latency_ms: float
    total_time_to_first_token_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class LLMProviderTelemetry:
    """Collect bounded counters and emit redacted request events.

    Request IDs are correlation fields in logs only. They are never used as a
    metric dimension, and prompt content and credentials are not accepted by
    this API.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests = 0
        self._successes = 0
        self._failures = 0
        self._attempts = 0
        self._retries = 0
        self._streams = 0
        self._stream_interruptions = 0
        self._latency_ms = 0.0
        self._ttft_ms = 0.0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._total_tokens = 0

    def started(self, request: CompletionRequest, *, stream: bool) -> float:
        with self._lock:
            self._requests += 1
            if stream:
                self._streams += 1
        return perf_counter()

    def succeeded(
        self,
        request: CompletionRequest,
        result: CompletionResult,
        *,
        started_at: float,
        first_token_ms: float | None = None,
        stream: bool = False,
    ) -> None:
        attempts = result.attempts or ()
        usage = result.usage
        self._record(
            request=request,
            success=True,
            attempts=len(attempts) or result.attempt,
            latency_ms=(perf_counter() - started_at) * 1000,
            first_token_ms=first_token_ms,
            usage=(
                usage.prompt_tokens if usage else None,
                usage.completion_tokens if usage else None,
                usage.total_tokens if usage else None,
            ),
            attribution=result.attribution,
            error_code=None,
            stream=stream,
        )

    def failed(
        self,
        request: CompletionRequest,
        error: LLMProviderError,
        *,
        started_at: float,
        first_token_ms: float | None = None,
        stream: bool = False,
    ) -> None:
        self._record(
            request=request,
            success=False,
            attempts=len(error.attempts) or error.attempt,
            latency_ms=(perf_counter() - started_at) * 1000,
            first_token_ms=first_token_ms,
            usage=(None, None, None),
            attribution=error.attribution,
            error_code=error.code.value,
            stream=stream,
        )

    def cancelled(
        self,
        request: CompletionRequest,
        *,
        started_at: float,
        stream: bool = False,
    ) -> None:
        """Record cancellation while allowing framework cancellation to propagate."""
        with self._lock:
            self._failures += 1
            self._latency_ms += max(0.0, (perf_counter() - started_at) * 1000)
            if stream:
                self._stream_interruptions += 1
        log_event(
            _logger,
            event="llm_provider_request_cancelled",
            message="LLM provider request was cancelled",
            level=logging.INFO,
            error_code="cancelled",
            fields={
                "request_id": request.request_id,
                "operation": request.operation,
                "route": request.route.alias,
                "stream": stream,
            },
        )

    def snapshot(self) -> LLMProviderTelemetrySnapshot:
        with self._lock:
            return LLMProviderTelemetrySnapshot(
                requests=self._requests,
                successes=self._successes,
                failures=self._failures,
                attempts=self._attempts,
                retries=self._retries,
                streams=self._streams,
                stream_interruptions=self._stream_interruptions,
                total_latency_ms=self._latency_ms,
                total_time_to_first_token_ms=self._ttft_ms,
                prompt_tokens=self._prompt_tokens,
                completion_tokens=self._completion_tokens,
                total_tokens=self._total_tokens,
            )

    def _record(
        self,
        *,
        request: CompletionRequest,
        success: bool,
        attempts: int,
        latency_ms: float,
        first_token_ms: float | None,
        usage: tuple[int | None, int | None, int | None],
        attribution: LLMAttribution | None,
        error_code: str | None,
        stream: bool,
    ) -> None:
        deployment_id = attribution.deployment_id if attribution else None
        key_fingerprint = attribution.key_fingerprint if attribution else None
        operation = request.operation[:80]
        route = request.route.alias[:80]
        with self._lock:
            self._attempts += max(1, attempts)
            self._retries += max(0, attempts - 1)
            self._latency_ms += max(0.0, latency_ms)
            if first_token_ms is not None:
                self._ttft_ms += max(0.0, first_token_ms)
            if success:
                self._successes += 1
            else:
                self._failures += 1
                if error_code == "stream_interrupted":
                    self._stream_interruptions += 1
            for value, name in zip(
                usage,
                ("prompt_tokens", "completion_tokens", "total_tokens"),
                strict=True,
            ):
                if isinstance(value, int) and value >= 0:
                    if name == "prompt_tokens":
                        self._prompt_tokens += value
                    elif name == "completion_tokens":
                        self._completion_tokens += value
                    else:
                        self._total_tokens += value
        log_event(
            _logger,
            event="llm_provider_request",
            message="LLM provider request completed",
            level=logging.INFO if success else logging.WARNING,
            error_code=error_code,
            fields={
                "request_id": request.request_id,
                "operation": operation,
                "route": route,
                "deployment_id": deployment_id,
                "key_fingerprint": key_fingerprint,
                "attempts": attempts,
                "retry_count": max(0, attempts - 1),
                "latency_ms": round(max(0.0, latency_ms), 3),
                "time_to_first_token_ms": (
                    round(first_token_ms, 3) if first_token_ms is not None else None
                ),
                "stream": stream,
                "prompt_tokens": usage[0],
                "completion_tokens": usage[1],
                "total_tokens": usage[2],
            },
        )
