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


def calculate_kelly_and_verdict(scenarios: dict) -> dict:
    """
    Pure Python function: Calculates mathematical indicators based on LLM-provided probabilities.
    Returns calculated final_verdict, kelly_confidence, and expected_value.
    """

    # 1. Extract probabilities (clean string or float)
    def parse_prob(val):
        if isinstance(val, str):
            return float(val.replace("%", "")) / 100 if "%" in val else float(val)
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    p_bull = parse_prob(scenarios.get("bull_case", {}).get("probability", 0))
    p_bear = parse_prob(scenarios.get("bear_case", {}).get("probability", 0))
    p_base = parse_prob(scenarios.get("base_case", {}).get("probability", 0))

    # Normalize probabilities (ensure they sum to 1.0)
    total_prob = p_bull + p_bear + p_base
    if total_prob == 0:
        p_bull, p_bear, p_base = 0.33, 0.33, 0.34
    else:
        p_bull /= total_prob
        p_bear /= total_prob
        p_base /= total_prob

    # 2. Define payoff map (Return on investment for each scenario)
    payoff_map = {
        "SURGE": 0.25,
        "MODERATE_UP": 0.10,
        "FLAT": 0.0,
        "MODERATE_DOWN": -0.10,
        "CRASH": -0.25,
    }

    def get_return(case_key):
        impl = scenarios.get(case_key, {}).get("price_implication", "FLAT")
        if hasattr(impl, "value"):  # Handle Enums
            impl = impl.value
        impl = str(impl).upper()

        for key, val in payoff_map.items():
            if key in impl:
                return val
        return 0.0

    r_bull = get_return("bull_case")
    r_bear = get_return("bear_case")
    r_base = get_return("base_case")

    # 3. Calculate Expected Value (EV)
    ev = (p_bull * r_bull) + (p_bear * r_bear) + (p_base * r_base)

    # 4. Calculate Kelly-style Confidence
    kelly_fraction = 0.0
    final_verdict = "NEUTRAL"
    if ev > 0.015:
        final_verdict = "LONG"
        kelly_fraction = min(ev / 0.05, 1.0)
    elif ev < -0.015:
        final_verdict = "SHORT"
        kelly_fraction = min(abs(ev) / 0.05, 1.0)

    # 5. Safety Lock (Hard Risk Control)
    bear_impl = str(scenarios.get("bear_case", {}).get("price_implication", "")).upper()
    if p_bear > 0.40:
        if final_verdict == "LONG":
            final_verdict = "NEUTRAL"
            kelly_fraction = 0.0
    elif "CRASH" in bear_impl and p_bear > 0.30:
        if final_verdict == "LONG":
            final_verdict = "NEUTRAL"
            kelly_fraction = 0.0

    return {
        "final_verdict": final_verdict,
        "kelly_confidence": round(float(kelly_fraction), 2),
        "expected_value": round(float(ev), 4),
    }
