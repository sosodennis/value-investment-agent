"""
Utility functions for debate agent enhancements.
Includes sycophancy detection using FastEmbed.
"""

import numpy as np
from fastembed import TextEmbedding


class SycophancyDetector:
    """
    Detects excessive agreement between Bull and Bear agents using embeddings.
    Uses FastEmbed with sentence-transformers/all-MiniLM-L6-v2 for lightweight CPU-based similarity.
    """

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """Initialize the embedding model (cached after first download)."""
        self._embedding_model: TextEmbedding | None = None
        self.model_name = model_name

    @property
    def embedding_model(self) -> TextEmbedding:
        """Lazy load the embedding model."""
        if self._embedding_model is None:
            self._embedding_model = TextEmbedding(model_name=self.model_name)
        return self._embedding_model

    def cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        return float(dot_product / (norm1 * norm2))

    def check_consensus(
        self, bull_thesis: str, bear_thesis: str, threshold: float = 0.8
    ) -> tuple[float, bool]:
        """
        Check if Bull and Bear theses are too similar (sycophancy).

        Args:
            bull_thesis: The Bull agent's argument
            bear_thesis: The Bear agent's argument
            threshold: Similarity threshold (default 0.75)

        Returns:
            tuple: (similarity_score, is_sycophantic)
                - similarity_score: Cosine similarity (0.0 to 1.0)
                - is_sycophantic: True if similarity > threshold
        """
        # Generate embeddings
        embeddings = list(self.embedding_model.embed([bull_thesis, bear_thesis]))

        # Extract vectors
        bull_vec = np.array(embeddings[0])
        bear_vec = np.array(embeddings[1])

        # Calculate similarity
        similarity = self.cosine_similarity(bull_vec, bear_vec)

        return similarity, similarity > threshold


# Global instance (lazy-loaded)
_detector: SycophancyDetector | None = None


def get_sycophancy_detector() -> SycophancyDetector:
    """Get or create the global sycophancy detector instance."""
    global _detector
    if _detector is None:
        _detector = SycophancyDetector()
    return _detector
