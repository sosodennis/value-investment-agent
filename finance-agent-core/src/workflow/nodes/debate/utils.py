"""
Utility functions for debate agent enhancements.
Includes sycophancy detection using FastEmbed and CAPM-based hurdle rate calculation.
"""

import numpy as np
from fastembed import TextEmbedding

from src.utils.logger import get_logger

from .market_data import (
    get_current_risk_free_rate,
    get_dynamic_payoff_map,
)

logger = get_logger(__name__)


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

    核心哲學：
    1. 只有兩個變數重要：潛在獲利 (Upside) 和 潛在虧損 (Downside)。
    2. 波動不是風險，"永久性虧損" 才是風險。
    3. 如果賠率 (Odds) 夠好，我們就賭。
    """
    scenarios = conclusion_data.get("scenario_analysis", {})
    risk_profile = conclusion_data.get("risk_profile", "GROWTH_TECH")

    # 1. 提取基本數據
    # 這裡我們使用與之前相同的 normalized 概率 helpers, 確保概率和為 1 (或接近)
    p_bull, p_bear, p_base = _get_normalized_probabilities(scenarios)

    # 獲取回報值 (使用 Payoff Map，動態映射 LLM 的 price_implication)
    payoff_map = get_dynamic_payoff_map(ticker, risk_profile)
    r_bull = _get_return_from_scenario(scenarios, "bull_case", payoff_map)
    r_base = _get_return_from_scenario(scenarios, "base_case", payoff_map)
    r_bear = _get_return_from_scenario(scenarios, "bear_case", payoff_map)

    # 2. 計算加權期望值 (EV)
    # 這是我們的 "羅盤"，告訴我們大方向
    raw_ev = (p_bull * r_bull) + (p_base * r_base) + (p_bear * r_bear)

    # 3. 計算 "機會成本" (Alpha)
    # 這是唯一的 "過濾器"：如果連美債都跑不贏，就別玩了
    risk_free = get_current_risk_free_rate()
    alpha = raw_ev - risk_free

    # 4. 核心邏輯：盈虧比 (Reward / Risk Ratio)
    # 我們只關心：看對了賺多少(Upside) vs 看錯了賠多少(Downside)

    # Upside Potential (只看漲的情境)
    # 這裡我們稍微修改一下 User 的邏輯，讓 Base Case 如果是正的也算 Upside
    weighted_upside = (p_bull * r_bull) + (p_base * max(0, r_base))

    # Downside Risk (只看跌的情境，取絕對值)
    # 我們加一點權重(1.5倍)，代表我們稍微討厭賠錢，但不要像之前 Lambda 那麼誇張
    weighted_downside = (p_bear * abs(r_bear)) + (p_base * abs(min(0, r_base)))
    weighted_downside = weighted_downside * 1.5

    # --- 數據質量檢查 (Data Quality Gate) ---
    # 如果 downside 接近 0，這通常是數據錯誤或 LLM Hallucination，不是真正的無風險套利
    data_quality_issue = False
    if weighted_downside < 0.001:
        # 檢查是否是合理的「無風險」情境（例如國債、貨幣基金）
        # 如果不是，這是數據錯誤
        if abs(r_bear) < 0.01 and abs(r_base) < 0.01:
            # Bear 和 Base 都接近 0，這不合理（除非是現金等價物）
            data_quality_issue = True
            # 強制設定一個最小風險，避免除以零
            weighted_downside = 0.05  # 假設至少有 5% 的潛在虧損
        else:
            # 真正的低風險情境（例如 p_bear 很低）
            rr_ratio = 10.0  # 保留原邏輯
    else:
        rr_ratio = weighted_upside / weighted_downside

    # --- 5. 最終判決 (簡單明瞭) ---

    direction = "NEUTRAL"
    bias = "FLAT"
    conviction = 50

    # 🚨 數據質量覆蓋 (Data Quality Override)
    if data_quality_issue:
        direction = "NEUTRAL"
        bias = "UNCERTAIN"
        conviction = 30  # 低信心
        logger.warning(
            f"⚠️ Data Quality Issue detected for {ticker}: "
            f"Near-zero downside (r_bear={r_bear:.4f}, r_base={r_base:.4f}). "
            f"Forcing NEUTRAL verdict."
        )
    else:
        # 條件 A: 顯著看多
        # 賠率 > 2.0 (賺的潛力是賠的兩倍) 且 Alpha 是正的
        if rr_ratio > 2.0 and alpha > 0:
            direction = "STRONG_LONG"
            bias = "BULLISH"
            conviction = 90

        # 條件 B: 普通看多
        # 賠率 > 1.3 (稍微划算) 且 Alpha 是正的
        elif rr_ratio > 1.3 and alpha > 0:
            direction = "LONG"
            bias = "BULLISH"
            conviction = 70

        # 條件 C: 必須做空 (垃圾股)
        # 期望值跑輸美債，且 賠率很差 (賺的潛力 < 賠的風險)
        elif alpha < 0 and rr_ratio < 0.8:
            direction = "SHORT"
            bias = "BEARISH"
            conviction = 70

        # 條件 D: 雞肋 / 觀望
        else:
            # 如果 Alpha 是負的，但賠率還可以 (rr_ratio > 1)，說明是 "食之無味棄之考慮"
            if alpha < 0:
                direction = "AVOID"  # 建議別買，但也別空
                bias = "BEARISH"
            else:
                direction = "NEUTRAL"  # 真的沒方向
                bias = "FLAT"

    return {
        "ticker": ticker,
        "final_verdict": direction,
        "analysis_bias": bias,
        "rr_ratio": round(rr_ratio, 2),  # 這是最直觀的指標
        "alpha": round(alpha, 4),
        "raw_ev": round(raw_ev, 4),
        "conviction": conviction,
        "model_summary": f"Reward/Risk: {rr_ratio:.2f}x, Alpha: {alpha:.2%}",
        "risk_free_benchmark": round(risk_free, 4),
        "data_quality_warning": data_quality_issue,  # 新增：數據質量警告
    }


def compress_financial_data(financial_reports: list[dict]) -> list[dict]:
    """
    Compresses raw SEC financial reports by removing metadata and flattening the structure.
    Optimizes for LLM context window.
    """
    compressed = []
    for report in financial_reports:
        # Extract basic info
        base = report.get("base") or {}
        ext = report.get("extension") or {}

        # We care about the year and the numerical values
        year = base.get("fiscal_year", {}).get("value", "Unknown")

        # Flattened metrics
        metrics = {}

        # Helper to extract value safely
        def get_val(item):
            if isinstance(item, dict):
                return item.get("value")
            return item

        # Base metrics
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

        # Extension metrics
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
    Compresses news research output by removing full content and technical metadata.
    """
    if not news_output or "news_items" not in news_output:
        return []

    compressed = []
    for item in news_output.get("news_items", []):
        analysis = item.get("analysis") or {}

        # Focus on the summary and key facts
        compressed_item = {
            "date": item.get("published_at", "N/A")[:10],  # Just YYYY-MM-DD
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
    Focuses on semantic tags and key metrics, removes raw data.
    """
    if not ta_output:
        return None

    # Extract key information
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
