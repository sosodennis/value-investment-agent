"""
Utility functions for debate agent enhancements.
Includes sycophancy detection using FastEmbed and CAPM-based hurdle rate calculation.
"""

import numpy as np
from fastembed import TextEmbedding

from src.common.tools.logger import get_logger

from .market_data import (
    get_current_risk_free_rate,
    get_dynamic_payoff_map,
)

logger = get_logger(__name__)


class SycophancyDetector:
    """
    Detects excessive agreement between Bull and Bear agents using embeddings.
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


def _parse_score(val) -> float:
    """Helper to parse probability scores from various formats."""
    if isinstance(val, str):
        val = val.replace("%", "").strip()
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _get_normalized_probabilities(scenarios: dict) -> tuple[float, float, float]:
    """Extract and normalize probabilities for bull, bear, and base cases."""
    s_bull = _parse_score(scenarios.get("bull_case", {}).get("probability", 0))
    s_bear = _parse_score(scenarios.get("bear_case", {}).get("probability", 0))
    s_base = _parse_score(scenarios.get("base_case", {}).get("probability", 0))

    total_score = s_bull + s_bear + s_base
    if total_score == 0:
        return 0.33, 0.33, 0.34
    return s_bull / total_score, s_bear / total_score, s_base / total_score


def _get_return_from_scenario(
    scenarios: dict, case_key: str, payoff_map: dict
) -> float:
    """Map price implication strings to numerical return values."""
    impl = scenarios.get(case_key, {}).get("price_implication", "FLAT")
    if hasattr(impl, "value"):
        impl = impl.value
    impl = str(impl).upper()

    for k, v in payoff_map.items():
        if k in impl:
            return v
    return 0.0


def calculate_pragmatic_verdict(conclusion_data: dict, ticker: str = None) -> dict:
    """
    V2.0 Simplified: The Pragmatic Reward/Risk Model
    """
    scenarios = conclusion_data.get("scenario_analysis", {})
    risk_profile = conclusion_data.get("risk_profile", "GROWTH_TECH")

    p_bull, p_bear, p_base = _get_normalized_probabilities(scenarios)

    payoff_map = get_dynamic_payoff_map(ticker, risk_profile)
    r_bull = _get_return_from_scenario(scenarios, "bull_case", payoff_map)
    r_base = _get_return_from_scenario(scenarios, "base_case", payoff_map)
    r_bear = _get_return_from_scenario(scenarios, "bear_case", payoff_map)

    raw_ev = (p_bull * r_bull) + (p_base * r_base) + (p_bear * r_bear)

    risk_free = get_current_risk_free_rate()
    alpha = raw_ev - risk_free

    weighted_upside = (p_bull * r_bull) + (p_base * max(0, r_base))

    weighted_downside = (p_bear * abs(r_bear)) + (p_base * abs(min(0, r_base)))
    weighted_downside = weighted_downside * 1.5

    data_quality_issue = False
    if weighted_downside < 0.001:
        if abs(r_bear) < 0.01 and abs(r_base) < 0.01:
            data_quality_issue = True
            weighted_downside = 0.05
        else:
            rr_ratio = 10.0
    else:
        rr_ratio = weighted_upside / weighted_downside

    direction = "NEUTRAL"
    bias = "FLAT"
    conviction = 50

    if data_quality_issue:
        direction = "NEUTRAL"
        bias = "UNCERTAIN"
        conviction = 30
        logger.warning(
            f"⚠️ Data Quality Issue detected for {ticker}: "
            f"Near-zero downside (r_bear={r_bear:.4f}, r_base={r_base:.4f}). "
            f"Forcing NEUTRAL verdict."
        )
    else:
        if rr_ratio > 2.0 and alpha > 0:
            direction = "STRONG_LONG"
            bias = "BULLISH"
            conviction = 90
        elif rr_ratio > 1.3 and alpha > 0:
            direction = "LONG"
            bias = "BULLISH"
            conviction = 70
        elif alpha < 0 and rr_ratio < 0.8:
            direction = "SHORT"
            bias = "BEARISH"
            conviction = 70
        else:
            if alpha < 0:
                direction = "AVOID"
                bias = "BEARISH"
            else:
                direction = "NEUTRAL"
                bias = "FLAT"

    return {
        "ticker": ticker,
        "final_verdict": direction,
        "analysis_bias": bias,
        "rr_ratio": round(rr_ratio, 2),
        "alpha": round(alpha, 4),
        "raw_ev": round(raw_ev, 4),
        "conviction": conviction,
        "model_summary": f"Reward/Risk: {rr_ratio:.2f}x, Alpha: {alpha:.2%}",
        "risk_free_benchmark": round(risk_free, 4),
        "data_quality_warning": data_quality_issue,
    }


def compress_financial_data(financial_reports: list[dict]) -> list[dict]:
    """
    Compresses raw SEC financial reports.
    """
    compressed = []
    for report in financial_reports:
        base = report.get("base") or {}
        ext = report.get("extension") or {}
        year = base.get("fiscal_year", {}).get("value", "Unknown")

        metrics = {}

        def get_val(item):
            if isinstance(item, dict):
                return item.get("value")
            return item

        main_fields = [
            "total_revenue",
            "net_income",
            "operating_cash_flow",
            "total_assets",
            "total_liabilities",
            "total_equity",
            "cash_and_equivalents",
            "shares_outstanding",
        ]
        for field in main_fields:
            val = get_val(base.get(field))
            if val is not None:
                metrics[field] = val

        ext_fields = [
            "inventory",
            "accounts_receivable",
            "cogs",
            "rd_expense",
            "sga_expense",
            "capex",
        ]
        for field in ext_fields:
            val = get_val(ext.get(field))
            if val is not None:
                metrics[field] = val

        compressed.append(
            {
                "fiscal_year": year,
                "metrics": metrics,
                "industry": report.get("industry_type", "Unknown"),
            }
        )

    return compressed


def compress_news_data(news_output: dict) -> list[dict]:
    """
    Compresses news research output.
    """
    if not news_output:
        return []

    news_items = news_output.get("news_items", [])
    compressed = []
    for item in news_items:
        analysis = item.get("analysis") or {}
        compressed_item = {
            "date": item.get("published_at", "N/A")[:10],
            "title": item.get("title"),
            "source": item.get("source", {}).get("name", "Unknown"),
            "summary": analysis.get("summary"),
            "sentiment": analysis.get("sentiment"),
            "impact": analysis.get("impact_level"),
            "key_facts": [f.get("content") for f in analysis.get("key_facts", [])],
        }
        compressed.append(compressed_item)

    return compressed


def compress_ta_data(ta_output: dict | None) -> dict | None:
    """
    Compresses technical analysis output for debate context.
    """
    if not ta_output:
        return None

    compressed = {
        "ticker": ta_output.get("ticker"),
        "timestamp": ta_output.get("timestamp"),
        "signal_summary": {
            "z_score": ta_output.get("signal_state", {}).get("z_score"),
            "direction": ta_output.get("signal_state", {}).get("direction"),
            "risk_level": ta_output.get("signal_state", {}).get("risk_level"),
            "statistical_state": ta_output.get("signal_state", {}).get(
                "statistical_state"
            ),
        },
        "memory_metrics": {
            "optimal_d": ta_output.get("frac_diff_metrics", {}).get("optimal_d"),
            "memory_strength": ta_output.get("frac_diff_metrics", {}).get(
                "memory_strength"
            ),
        },
        "semantic_tags": ta_output.get("semantic_tags", []),
        "interpretation": ta_output.get("llm_interpretation"),
    }

    return compressed
