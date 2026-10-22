from __future__ import annotations

from collections.abc import Sequence
from threading import Lock

from src.model_inference.application.service import ModelInferenceService
from src.model_inference.domain.contracts import (
    FLSResult,
    ModelInference,
    NewsSentimentResult,
)
from src.model_inference.infrastructure.http_adapter import HttpInferenceAdapter
from src.model_inference.infrastructure.settings import ModelInferenceSettings

_default_model_inference: ModelInferenceService | None = None
_default_model_inference_lock = Lock()


class _DefaultModelInference(ModelInference):
    async def news_sentiment(self, text: str) -> NewsSentimentResult:
        return await get_default_model_inference().news_sentiment(text)

    def news_sentiment_sync(self, text: str) -> NewsSentimentResult:
        return get_default_model_inference().news_sentiment_sync(text)

    def fls_predictions(self, sentences: Sequence[str]) -> FLSResult:
        return get_default_model_inference().fls_predictions(sentences)


_model_inference = _DefaultModelInference()


def get_default_model_inference() -> ModelInferenceService:
    global _default_model_inference
    with _default_model_inference_lock:
        if _default_model_inference is None:
            settings = ModelInferenceSettings.from_environment()
            _default_model_inference = ModelInferenceService(
                HttpInferenceAdapter(settings)
            )
        return _default_model_inference


async def close_default_model_inference() -> None:
    global _default_model_inference
    with _default_model_inference_lock:
        service = _default_model_inference
        _default_model_inference = None
    if service is not None:
        await service.aclose()


def get_model_inference() -> ModelInference:
    return _model_inference
