from __future__ import annotations

from typing import Protocol

from src.model_inference.domain.contracts import (
    InferenceRequest,
    InferenceResult,
)


class InferenceTransport(Protocol):
    def infer(self, request: InferenceRequest) -> InferenceResult: ...

    async def infer_async(self, request: InferenceRequest) -> InferenceResult: ...

    async def aclose(self) -> None: ...
