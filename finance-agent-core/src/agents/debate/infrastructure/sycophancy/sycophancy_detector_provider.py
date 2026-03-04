from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from fastembed import TextEmbedding

from src.shared.kernel.tools.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SycophancyDetectorProvider:
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"
    _embedding_model: TextEmbedding | None = None

    @staticmethod
    def _local_files_only() -> bool:
        return os.getenv("HF_LOCAL_FILES_ONLY", "1").strip().lower() not in {
            "0",
            "false",
            "no",
        }

    @staticmethod
    def _cache_dir() -> str | None:
        value = os.getenv("FASTEMBED_CACHE_PATH")
        if isinstance(value, str) and value.strip():
            return value
        return None

    @property
    def embedding_model(self) -> TextEmbedding:
        if self._embedding_model is None:
            self._embedding_model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=self._cache_dir(),
                local_files_only=self._local_files_only(),
            )
        return self._embedding_model

    @staticmethod
    def _cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        return float(dot_product / (norm1 * norm2))

    def check_consensus(
        self, bull_thesis: str, bear_thesis: str, threshold: float = 0.8
    ) -> tuple[float, bool]:
        embeddings = list(self.embedding_model.embed([bull_thesis, bear_thesis]))
        bull_vec = np.array(embeddings[0])
        bear_vec = np.array(embeddings[1])
        similarity = self._cosine_similarity(bull_vec, bear_vec)
        return similarity, similarity > threshold


_detector: SycophancyDetectorProvider | None = None


def get_sycophancy_detector_provider() -> SycophancyDetectorProvider:
    global _detector
    if _detector is None:
        _detector = SycophancyDetectorProvider()
    return _detector
