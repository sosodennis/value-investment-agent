"""
Unit tests for Technical Analysis node.
"""

import numpy as np
import pandas as pd


def test_find_optimal_d_returns_valid_range():
    """Test that optimal d value is between 0 and 1."""
    from src.agents.technical.data.tools import find_optimal_d

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
    from src.agents.technical.data.tools import frac_diff_ffd

    # Create synthetic price series
    np.random.seed(42)
    prices = pd.Series(100 + np.cumsum(np.random.randn(500) * 0.5))

    fd_series = frac_diff_ffd(prices, d=0.5)

    assert isinstance(fd_series, pd.Series), "Output should be pandas Series"
    assert len(fd_series) > 0, "Output should not be empty"
    assert len(fd_series) <= len(prices), "Output length should be <= input length"


def test_compute_z_score():
    """Test Z-score computation."""
    from src.agents.technical.data.tools import compute_z_score

    # Create synthetic FracDiff series
    np.random.seed(42)
    fd_series = pd.Series(np.random.randn(300))

    z_score = compute_z_score(fd_series, lookback=252)

    assert isinstance(z_score, float), "Z-score should be float"
    assert not np.isnan(z_score), "Z-score should not be NaN"
    assert not np.isinf(z_score), "Z-score should not be infinite"


def test_semantic_tags_mapping():
    """Test that semantic tags are correctly mapped based on thresholds."""
    from src.agents.technical.domain.models import (
        SemanticConfluenceInput,
        SemanticTagPolicyInput,
    )
    from src.agents.technical.domain.policies import assemble_semantic_tags

    dummy_confluence = SemanticConfluenceInput(
        bollinger_state="INSIDE",
        statistical_strength=50.0,
        macd_momentum="NEUTRAL",
        obv_state="NEUTRAL",
        obv_z=0.0,
    )

    # Test case 1: Low d, low Z
    tags_result = assemble_semantic_tags(
        SemanticTagPolicyInput(
            z_score=0.5,
            optimal_d=0.2,
            confluence=dummy_confluence,
        )
    )
    assert tags_result.memory_strength == "structurally_stable"
    assert tags_result.statistical_state == "equilibrium"
    assert tags_result.risk_level == "low"

    # Test case 2: High d, high Z
    tags_result = assemble_semantic_tags(
        SemanticTagPolicyInput(
            z_score=2.5,
            optimal_d=0.7,
            confluence=dummy_confluence,
        )
    )
    assert tags_result.memory_strength == "fragile"
    assert tags_result.statistical_state == "anomaly"
    assert tags_result.risk_level == "critical"

    # Test case 3: Balanced d, medium Z
    tags_result = assemble_semantic_tags(
        SemanticTagPolicyInput(
            z_score=1.5,
            optimal_d=0.4,
            confluence=dummy_confluence,
        )
    )
    assert tags_result.memory_strength == "balanced"
    assert tags_result.statistical_state == "deviating"
    assert tags_result.risk_level == "medium"


def test_compress_ta_data():
    """Test TA data compression for debate."""
    from src.agents.debate.domain.services import compress_ta_data

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
    from src.agents.debate.domain.services import compress_ta_data

    result = compress_ta_data(None)
    assert result is None
