from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Literal, Protocol


class InferenceOperation(str, Enum):
    NEWS_SENTIMENT = "news.sentiment"
    SEC_FLS = "sec.fls"


@dataclass(frozen=True, slots=True)
class OperationPolicy:
    default_deadline_ms: int
    maximum_deadline_ms: int
    max_text_chars: int | None = None
    max_sentences: int | None = None
    max_sentence_chars: int | None = None


OPERATION_POLICIES: Mapping[InferenceOperation, OperationPolicy] = MappingProxyType(
    {
        InferenceOperation.NEWS_SENTIMENT: OperationPolicy(
            default_deadline_ms=500,
            maximum_deadline_ms=1_000,
            max_text_chars=12_000,
        ),
        InferenceOperation.SEC_FLS: OperationPolicy(
            default_deadline_ms=750,
            maximum_deadline_ms=1_500,
            max_sentences=120,
            max_sentence_chars=2_000,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class NewsSentimentInput:
    text: str


@dataclass(frozen=True, slots=True)
class FLSSentencesInput:
    sentences: tuple[str, ...]


InferenceInput = NewsSentimentInput | FLSSentencesInput


@dataclass(frozen=True, slots=True)
class InferenceRequest:
    operation: InferenceOperation
    input: InferenceInput
    request_id: str
    deadline_ms: int


@dataclass(frozen=True, slots=True)
class NewsSentimentResult:
    label: Literal["positive", "negative", "neutral"]
    confidence: float
    scores: Mapping[str, float]
    has_numbers: bool
    model_revision: str


@dataclass(frozen=True, slots=True)
class FLSPrediction:
    keep: bool
    confidence: float | None


@dataclass(frozen=True, slots=True)
class FLSResult:
    predictions: tuple[FLSPrediction, ...]
    model_revision: str


InferenceResult = NewsSentimentResult | FLSResult


class ModelInference(Protocol):
    async def news_sentiment(self, text: str) -> NewsSentimentResult: ...

    def news_sentiment_sync(self, text: str) -> NewsSentimentResult: ...

    def fls_predictions(self, sentences: Sequence[str]) -> FLSResult: ...
