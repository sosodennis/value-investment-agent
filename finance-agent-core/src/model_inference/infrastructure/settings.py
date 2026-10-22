from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelInferenceSettings:
    news_url: str
    fls_url: str
    token: str

    @classmethod
    def from_environment(cls) -> ModelInferenceSettings:
        return cls(
            news_url=os.getenv(
                "MODEL_INFERENCE_NEWS_URL", "http://localhost:8001"
            ).rstrip("/"),
            fls_url=os.getenv(
                "MODEL_INFERENCE_FLS_URL", "http://localhost:8001"
            ).rstrip("/"),
            token=os.getenv("MODEL_INFERENCE_TOKEN", ""),
        )
