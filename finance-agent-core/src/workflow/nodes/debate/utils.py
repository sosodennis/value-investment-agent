"""
Utility functions for debate agent enhancements.
Includes sycophancy detection using FastEmbed and CAPM-based hurdle rate calculation.
"""

import numpy as np
from fastembed import TextEmbedding

from .market_data import (
    calculate_capm_hurdle,
    get_dynamic_crash_impact,
    get_dynamic_payoff_map,
)


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


def calculate_kelly_and_verdict(conclusion_data: dict, ticker: str = None) -> dict:
    """
    V8.0: CAPM-Based Dynamic Hurdle Rate + Mean-Variance Kelly Optimization

    Integrates enterprise-level CAPM to replace hardcoded thresholds with
    market-driven Beta calculations. The Debate AI determines EV; CAPM sets
    the minimum required return based on the stock's historical volatility.

    Args:
        conclusion_data: Debate conclusion with scenario analysis
        ticker: Stock ticker symbol (optional, for real-time Beta calculation)

    Returns:
        Dict with verdict, kelly_confidence, and CAPM metrics
    """
    scenarios = conclusion_data.get("scenario_analysis", {})
    risk_profile = conclusion_data.get("risk_profile", "GROWTH_TECH")

    # --- 1. 解析分數與歸一化 (Normalization) ---
    # 優化點：移除 "v*100" 的 hack。利用歸一化的數學特性，
    # 無論輸入是 [0.8, 0.1, 0.1] 還是 [80, 10, 10]，結果都一樣。
    def parse_score(val):
        if isinstance(val, str):
            val = val.replace("%", "").strip()
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    s_bull = parse_score(scenarios.get("bull_case", {}).get("probability", 0))
    s_bear = parse_score(scenarios.get("bear_case", {}).get("probability", 0))
    s_base = parse_score(scenarios.get("base_case", {}).get("probability", 0))

    total_score = s_bull + s_bear + s_base
    if total_score == 0:
        p_bull, p_bear, p_base = 0.33, 0.33, 0.34
    else:
        p_bull = s_bull / total_score
        p_bear = s_bear / total_score
        p_base = s_base / total_score

    # --- 2. Dynamic Payoff Map (VaR Integration) ---
    # Get theory-based crash impact first so it is available in all branches
    crash_impact = get_dynamic_crash_impact(risk_profile)

    if ticker:
        # Use historical volatility for Upside, Theory-based for Downside
        payoff_map = get_dynamic_payoff_map(ticker, risk_profile)
    else:
        # Fallback: Use static map (for unit tests or missing ticker)
        payoff_map = {
            "SURGE": 0.25,
            "MODERATE_UP": 0.10,
            "FLAT": 0.0,
            "MODERATE_DOWN": -0.10,
            "CRASH": crash_impact,
        }

    def get_return(case_key):
        impl = scenarios.get(case_key, {}).get("price_implication", "FLAT")
        if hasattr(impl, "value"):
            impl = impl.value
        impl = str(impl).upper()
        for k, v in payoff_map.items():
            if k in impl:
                return v
        return 0.0

    r_bull = get_return("bull_case")
    r_bear = get_return("bear_case")
    r_base = get_return("base_case")

    # --- 3. EV & Variance Calculation ---
    ev = (p_bull * r_bull) + (p_bear * r_bear) + (p_base * r_base)

    # 方差 (Variance) = Sum(Prob * (Return - EV)^2)
    # 這代表了這筆交易的「不確定性」。如果 Bull=+50% 且 Bear=-50%，方差會極大，倉位會自動降低。
    variance = (
        (p_bull * (r_bull - ev) ** 2)
        + (p_bear * (r_bear - ev) ** 2)
        + (p_base * (r_base - ev) ** 2)
    )

    # --- 4. Enterprise CAPM Hurdle Rate ---
    if ticker:
        hurdle_rate, beta, data_source = calculate_capm_hurdle(ticker, risk_profile)
    else:
        # Static defaults for robustness
        from .market_data import (
            DEFAULT_MARKET_RISK_PREMIUM,
            DEFAULT_RISK_FREE_RATE,
            STATIC_BETA_MAP,
        )

        beta = STATIC_BETA_MAP.get(risk_profile.upper(), 1.5)
        annual_hurdle = DEFAULT_RISK_FREE_RATE + beta * DEFAULT_MARKET_RISK_PREMIUM
        hurdle_rate = annual_hurdle / 4.0
        data_source = "STATIC_FALLBACK"

    # --- 5. Mean-Variance Kelly Optimization ---
    kelly_fraction = 0.0
    final_verdict = "NEUTRAL"
    safe_variance = variance if variance > 0.0001 else 0.0001

    if ev > hurdle_rate:
        final_verdict = "LONG"
        # 廣義 Kelly 公式
        raw_kelly = ev / safe_variance
        # 應用 Half-Kelly (半凱利) 策略：業界標準，為了平滑波動，只使用計算值的一半
        kelly_fraction = raw_kelly * 0.5

    elif ev < -hurdle_rate:
        final_verdict = "SHORT"
        raw_kelly = abs(ev) / safe_variance
        kelly_fraction = raw_kelly * 0.5

    kelly_fraction = max(0.0, min(kelly_fraction, 1.0))

    # --- 6. Smart Safety Lock ---
    risk_profile_upper = risk_profile.upper()
    tolerance_map = {
        "DEFENSIVE_VALUE": 0.15,
        "GROWTH_TECH": 0.35,
        "SPECULATIVE_CRYPTO_BIO": 0.45,
    }
    crash_tolerance = tolerance_map.get(risk_profile_upper, 0.25)

    bear_impl = str(scenarios.get("bear_case", {}).get("price_implication", "")).upper()
    risk_override = False

    if p_bear > 0.55:
        risk_override = True
    elif "CRASH" in bear_impl and p_bear > crash_tolerance:
        risk_override = True

    if risk_override and final_verdict == "LONG":
        final_verdict = "NEUTRAL"
        kelly_confidence = 0.0
    else:
        kelly_confidence = kelly_fraction

    return {
        "final_verdict": final_verdict,
        "kelly_confidence": round(float(kelly_confidence), 2),
        "expected_value": round(float(ev), 4),
        "variance": round(float(variance), 4),
        "hurdle_rate": round(float(hurdle_rate), 4),
        "beta": round(float(beta), 2) if beta else None,
        "crash_impact": round(float(crash_impact), 2),
        "data_source": data_source,
        "risk_override": risk_override,
        "p_bull": round(p_bull, 2),
        "p_bear": round(p_bear, 2),
    }
