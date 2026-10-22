from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Operation = Literal["news.sentiment", "sec.fls"]
NewsLabel = Literal["positive", "negative", "neutral"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class InferenceRequest(StrictModel):
    schema_version: Literal["inference.v1"]
    operation: Operation
    deadline_ms: int | None = Field(default=None, ge=1)
    input: dict[str, object]


class NewsInput(StrictModel):
    text: str = Field(min_length=1, max_length=12_000)

    @field_validator("text")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank")
        return value


class FLSInput(StrictModel):
    sentences: list[str] = Field(min_length=1, max_length=120)

    @field_validator("sentences")
    @classmethod
    def validate_sentences(cls, value: list[str]) -> list[str]:
        for sentence in value:
            if not sentence.strip():
                raise ValueError("sentences must not contain blank values")
            if len(sentence) > 2_000:
                raise ValueError("each sentence must be at most 2000 characters")
        return value


class NewsResult(StrictModel):
    label: NewsLabel
    confidence: float = Field(ge=0.0, le=1.0)
    scores: dict[str, float]


class FLSPrediction(StrictModel):
    keep: bool
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class FLSResult(StrictModel):
    predictions: list[FLSPrediction]


class InferenceResponse(StrictModel):
    schema_version: Literal["inference.v1"]
    request_id: str
    operation: Operation
    model_revision: str
    result: NewsResult | FLSResult


class ErrorBody(StrictModel):
    code: str
    message: str
    retryable: bool
    retry_after_ms: int | None = None


class ErrorResponse(StrictModel):
    schema_version: Literal["inference.v1"]
    request_id: str
    error: ErrorBody
