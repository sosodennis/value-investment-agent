from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceError(Exception):
    code: str
    status_code: int
    message: str
    retryable: bool = False
    retry_after_ms: int | None = None


def invalid_argument(message: str) -> ServiceError:
    return ServiceError("INVALID_ARGUMENT", 400, message)


def unauthenticated() -> ServiceError:
    return ServiceError("UNAUTHENTICATED", 401, "service authentication required")


def model_not_ready(message: str = "model is not ready") -> ServiceError:
    return ServiceError("MODEL_NOT_READY", 503, message, True, 1_000)


def overloaded() -> ServiceError:
    return ServiceError("OVERLOADED", 429, "inference capacity is full", True, 250)


def deadline_exceeded() -> ServiceError:
    return ServiceError(
        "DEADLINE_EXCEEDED",
        504,
        "inference deadline exceeded",
        True,
        100,
    )


def cancelled() -> ServiceError:
    return ServiceError("CANCELLED", 499, "inference request was cancelled")


def unavailable(message: str = "inference service is unavailable") -> ServiceError:
    return ServiceError("UNAVAILABLE", 503, message, True, 250)


def inference_failed() -> ServiceError:
    return ServiceError("INFERENCE_FAILED", 500, "model inference failed")
