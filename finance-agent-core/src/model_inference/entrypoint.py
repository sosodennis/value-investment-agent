from __future__ import annotations

from src.model_inference.application.wiring import (
    close_default_model_inference,
)
from src.model_inference.application.wiring import (
    get_model_inference as get_model_inference_proxy,
)
from src.model_inference.domain.contracts import (
    FLSPrediction,
    FLSResult,
    ModelInference,
    NewsSentimentResult,
)
from src.model_inference.domain.errors import InferenceErrorCode, InferenceFailure


def get_model_inference() -> ModelInference:
    return get_model_inference_proxy()


async def close_model_inference() -> None:
    await close_default_model_inference()


__all__ = [
    "FLSPrediction",
    "FLSResult",
    "InferenceErrorCode",
    "InferenceFailure",
    "ModelInference",
    "NewsSentimentResult",
    "close_model_inference",
    "get_model_inference",
]
