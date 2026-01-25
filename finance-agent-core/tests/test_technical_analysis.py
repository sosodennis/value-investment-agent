"""
Unit tests for Technical Analysis node.
"""

import numpy as np
import pandas as pd


def test_find_optimal_d_returns_valid_range():
    """Test that optimal d value is between 0 and 1."""
    from src.workflow.nodes.technical_analysis.tools import find_optimal_d

    # Create synthetic price series with trend
    np.random.seed(42)
    prices = pd.Series(100 + np.cumsum(np.random.randn(500) * 0.5))

    optimal_d, window_length, adf_stat, adf_pvalue = find_optimal_d(prices)

    assert 0.0 <= optimal_d <= 1.0, f"d value {optimal_d} out of range [0, 1]"
    assert window_length > 0, "Window length should be positive"
    assert isinstance(adf_stat, float), "ADF statistic should be float"
    assert isinstance(adf_pvalue, float), "ADF p-value should be float"


def test_apply_fracdiff_preserves_structure():
    """Test that FracDiff output has expected structure."""
    from src.workflow.nodes.technical_analysis.tools import frac_diff_ffd

    # Create synthetic price series
    np.random.seed(42)
    prices = pd.Series(100 + np.cumsum(np.random.randn(500) * 0.5))

    fd_series = frac_diff_ffd(prices, d=0.5)

    assert isinstance(fd_series, pd.Series), "Output should be pandas Series"
    assert len(fd_series) > 0, "Output should not be empty"
    assert len(fd_series) <= len(prices), "Output length should be <= input length"


def test_compute_z_score():
    """Test Z-score computation."""
    from src.workflow.nodes.technical_analysis.tools import compute_z_score

    # Create synthetic FracDiff series
    np.random.seed(42)
    fd_series = pd.Series(np.random.randn(300))

    z_score = compute_z_score(fd_series, lookback=252)

    assert isinstance(z_score, float), "Z-score should be float"
    assert not np.isnan(z_score), "Z-score should not be NaN"
    assert not np.isinf(z_score), "Z-score should not be infinite"


def test_semantic_tags_mapping():
    """Test that semantic tags are correctly mapped based on thresholds."""
    from src.workflow.nodes.technical_analysis.semantic_layer import assembler
    from src.workflow.nodes.technical_analysis.structures import (
        MemoryStrength,
        RiskLevel,
        StatisticalState,
    )

    # Dummy data for confluence
    dummy_bb = {"state": "INSIDE"}
    dummy_stat = {"value": 50.0}
    dummy_macd = {"momentum_state": "NEUTRAL"}
    dummy_obv = {"fd_obv_z": 0.0, "state": "NEUTRAL"}

    # Test case 1: Low d, low Z
    tags_dict = assembler.assemble(
        z_score=0.5,
        optimal_d=0.2,
        bollinger_data=dummy_bb,
        stat_strength_data=dummy_stat,
        macd_data=dummy_macd,
        obv_data=dummy_obv,
    )
    assert tags_dict["memory_strength"] == MemoryStrength.STRUCTURALLY_STABLE
    assert tags_dict["statistical_state"] == StatisticalState.EQUILIBRIUM
    assert tags_dict["risk_level"] == RiskLevel.LOW

    # Test case 2: High d, high Z
    tags_dict = assembler.assemble(
        z_score=2.5,
        optimal_d=0.7,
        bollinger_data=dummy_bb,
        stat_strength_data=dummy_stat,
        macd_data=dummy_macd,
        obv_data=dummy_obv,
    )
    assert tags_dict["memory_strength"] == MemoryStrength.FRAGILE
    assert tags_dict["statistical_state"] == StatisticalState.STATISTICAL_ANOMALY
    assert tags_dict["risk_level"] == RiskLevel.CRITICAL

    # Test case 3: Balanced d, medium Z
    tags_dict = assembler.assemble(
        z_score=1.5,
        optimal_d=0.4,
        bollinger_data=dummy_bb,
        stat_strength_data=dummy_stat,
        macd_data=dummy_macd,
        obv_data=dummy_obv,
    )
    assert tags_dict["memory_strength"] == MemoryStrength.BALANCED
    assert tags_dict["statistical_state"] == StatisticalState.DEVIATING
    assert tags_dict["risk_level"] == RiskLevel.MEDIUM


def test_compress_ta_data():
    """Test TA data compression for debate."""
    from src.workflow.nodes.debate.utils import compress_ta_data

    # Mock TA output
    ta_output = {
        "ticker": "AAPL",
        "timestamp": "2026-01-19T00:00:00Z",
        "signal_state": {
            "z_score": 2.1,
            "direction": "BULLISH_EXTENSION",
            "risk_level": "CRITICAL",
            "statistical_state": "anomaly",
        },
        "frac_diff_metrics": {
            "optimal_d": 0.42,
            "memory_strength": "balanced",
        },
        "semantic_tags": ["MEMORY_BALANCED", "STATE_STATISTICAL_ANOMALY"],
        "llm_interpretation": "Test interpretation",
        "raw_data": {"price_series": {}, "fracdiff_series": {}},
    }

    compressed = compress_ta_data(ta_output)

    assert compressed is not None
    assert compressed["ticker"] == "AAPL"
    assert "raw_data" not in compressed
    assert compressed["signal_summary"]["z_score"] == 2.1
    assert compressed["memory_metrics"]["optimal_d"] == 0.42
    assert len(compressed["semantic_tags"]) == 2


def test_compress_ta_data_handles_none():
    """Test that compress_ta_data handles None input."""
    from src.workflow.nodes.debate.utils import compress_ta_data

    result = compress_ta_data(None)
    assert result is None
