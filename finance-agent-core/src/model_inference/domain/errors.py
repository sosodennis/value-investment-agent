from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InferenceErrorCode(str, Enum):
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    MODEL_NOT_READY = "MODEL_NOT_READY"
    OVERLOADED = "OVERLOADED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    CANCELLED = "CANCELLED"
    UNAVAILABLE = "UNAVAILABLE"
    INFERENCE_FAILED = "INFERENCE_FAILED"


@dataclass(frozen=True)
class InferenceFailure(Exception):
    code: InferenceErrorCode
    request_id: str
    retryable: bool
    retry_after_ms: int | None = None
    message: str = "model inference failed"

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)
