"""
Unit tests for CAPM-based market data calculations.

Tests cover:
- Beta calculation with mock data
- CAPM hurdle rate computation
- Fallback logic when market data is unavailable
- VaR-based crash impact scaling
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

# Add project root to path (must be before src imports)
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.workflow.nodes.debate.market_data import (  # noqa: E402
    STATIC_BETA_MAP,
    calculate_capm_hurdle,
    get_dynamic_crash_impact,
    get_stock_beta,
)


class TestBetaCalculation:
    """Test Beta calculation with various scenarios."""

    @patch("src.workflow.nodes.debate.market_data.yf.download")
    def test_beta_calculation_with_mock_data(self, mock_download):
        """Test Beta calculation with known returns."""
        # Create mock data with known correlation
        dates = pd.date_range(start="2023-01-01", periods=100, freq="D")

        # Stock returns are 1.5x market returns (Beta should be ~1.5)
        market_returns = np.random.randn(100) * 0.01
        stock_returns = market_returns * 1.5 + np.random.randn(100) * 0.005

        # yfinance returns a DataFrame with multi-level columns
        # We need to simulate the structure: df["Adj Close"][ticker]
        mock_adj_close = pd.DataFrame(
            {
                "AAPL": 100 * (1 + stock_returns).cumprod(),
                "SPY": 100 * (1 + market_returns).cumprod(),
            },
            index=dates,
        )

        # Mock the full yfinance structure
        mock_data = MagicMock()
        mock_data.__getitem__.return_value = mock_adj_close
        mock_data.empty = False

        mock_download.return_value = mock_data

        beta = get_stock_beta("AAPL", "SPY")

        assert beta is not None
        # Beta should be close to 1.5 (allowing some variance due to noise)
        assert 1.2 < beta < 1.8

    @patch("src.workflow.nodes.debate.market_data.yf.download")
    def test_beta_fallback_on_empty_data(self, mock_download):
        """Test fallback when yfinance returns empty data."""
        mock_download.return_value = pd.DataFrame()

        beta = get_stock_beta("INVALID_TICKER")

        assert beta is None

    @patch("src.workflow.nodes.debate.market_data.yf.download")
    def test_beta_fallback_on_insufficient_data(self, mock_download):
        """Test fallback when insufficient data points."""
        dates = pd.date_range(start="2023-01-01", periods=10, freq="D")
        mock_data = pd.DataFrame(
            {
                "AAPL": np.random.randn(10),
                "SPY": np.random.randn(10),
            },
            index=dates,
        )

        mock_download.return_value = mock_data

        beta = get_stock_beta("AAPL")

        assert beta is None


class TestCAPMHurdleRate:
    """Test CAPM hurdle rate calculations."""

    @patch("src.workflow.nodes.debate.market_data.get_stock_beta")
    def test_capm_hurdle_for_defensive_stock(self, mock_get_beta):
        """Low Beta (0.7) should produce ~8% annual hurdle."""
        mock_get_beta.return_value = 0.7

        quarterly_hurdle, beta, source = calculate_capm_hurdle(
            "KO",  # Coca-Cola (defensive)
            "DEFENSIVE_VALUE",
        )

        assert beta == 0.7
        assert source == "REAL_TIME"

        # CAPM: 4.5% + 0.7 * 5% = 7.5% annual
        # Quarterly: 7.5% / 4 = 1.875%
        expected_quarterly = (0.045 + 0.7 * 0.05) / 4
        assert abs(quarterly_hurdle - expected_quarterly) < 0.001

    @patch("src.workflow.nodes.debate.market_data.get_stock_beta")
    def test_capm_hurdle_for_speculative_stock(self, mock_get_beta):
        """High Beta (3.5) should produce ~22% annual hurdle."""
        mock_get_beta.return_value = 3.5

        quarterly_hurdle, beta, source = calculate_capm_hurdle(
            "GME",  # GameStop (speculative)
            "SPECULATIVE_CRYPTO_BIO",
        )

        assert beta == 3.5
        assert source == "REAL_TIME"

        # CAPM: 4.5% + 3.5 * 5% = 22% annual
        # Quarterly: 22% / 4 = 5.5%
        expected_quarterly = (0.045 + 3.5 * 0.05) / 4
        assert abs(quarterly_hurdle - expected_quarterly) < 0.001

    @patch("src.workflow.nodes.debate.market_data.get_stock_beta")
    def test_fallback_when_yfinance_unavailable(self, mock_get_beta):
        """Should fall back to static profile-based Beta."""
        mock_get_beta.return_value = None  # Simulate yfinance failure

        quarterly_hurdle, beta, source = calculate_capm_hurdle(
            "UNKNOWN_TICKER", "GROWTH_TECH"
        )

        # Should use static Beta for GROWTH_TECH (1.5)
        assert beta == STATIC_BETA_MAP["GROWTH_TECH"]
        assert source == "STATIC_FALLBACK"

        # CAPM: 4.5% + 1.5 * 5% = 12% annual
        expected_quarterly = (0.045 + 1.5 * 0.05) / 4
        assert abs(quarterly_hurdle - expected_quarterly) < 0.001


class TestCrashImpactScaling:
    """Test VaR-style crash impact for different risk profiles."""

    def test_crash_impact_defensive(self):
        """Defensive stocks should have -25% crash impact."""
        impact = get_dynamic_crash_impact("DEFENSIVE_VALUE")
        assert impact == -0.25

    def test_crash_impact_growth(self):
        """Growth stocks should have -35% crash impact."""
        impact = get_dynamic_crash_impact("GROWTH_TECH")
        assert impact == -0.35

    def test_crash_impact_speculative(self):
        """Speculative assets should have -60% crash impact."""
        impact = get_dynamic_crash_impact("SPECULATIVE_CRYPTO_BIO")
        assert impact == -0.60

    def test_crash_impact_unknown_profile(self):
        """Unknown profiles should default to -25%."""
        impact = get_dynamic_crash_impact("UNKNOWN_PROFILE")
        assert impact == -0.25


class TestIntegration:
    """Integration tests combining multiple components."""

    @patch("src.workflow.nodes.debate.market_data.get_stock_beta")
    def test_full_capm_workflow(self, mock_get_beta):
        """Test complete CAPM calculation workflow."""
        mock_get_beta.return_value = 2.0

        hurdle, beta, source = calculate_capm_hurdle(
            "NVDA", "GROWTH_TECH", risk_free_rate=0.045, market_risk_premium=0.05
        )

        # Verify all components
        assert beta == 2.0
        assert source == "REAL_TIME"

        # CAPM: 4.5% + 2.0 * 5% = 14.5% annual = 3.625% quarterly
        expected = (0.045 + 2.0 * 0.05) / 4
        assert abs(hurdle - expected) < 0.001


class TestDynamicPayoffMap:
    """Test volatility-based dynamic payoff map generation."""

    @patch("src.workflow.nodes.debate.market_data.yf.download")
    def test_dynamic_payoff_map_with_mock_data(self, mock_download):
        """Test payoff map generation with known volatility."""
        from src.workflow.nodes.debate.market_data import get_dynamic_payoff_map

        # Create mock data with known volatility
        dates = pd.date_range(start="2023-01-01", periods=252, freq="D")

        # Daily volatility ~1% → Annual ~15.8% → Quarterly ~8%
        np.random.seed(42)
        returns = np.random.randn(252) * 0.01
        prices = 100 * (1 + returns).cumprod()

        mock_df = pd.DataFrame({"Adj Close": prices}, index=dates)
        mock_download.return_value = mock_df

        payoff_map = get_dynamic_payoff_map("AAPL", "GROWTH_TECH")

        # Verify structure
        assert "SURGE" in payoff_map
        assert "MODERATE_UP" in payoff_map
        assert "CRASH" in payoff_map

        # SURGE should be ~2σ (around 16%)
        assert 0.10 < payoff_map["SURGE"] < 0.25

        # CRASH should be theory-based (-35% for GROWTH_TECH), NOT volatility-based
        assert payoff_map["CRASH"] == -0.35

    def test_payoff_map_crash_uses_theory_not_history(self):
        """Verify CRASH uses CRASH_IMPACT_MAP, not historical volatility (Turkey Problem protection)."""
        from src.workflow.nodes.debate.market_data import (
            CRASH_IMPACT_MAP,
            get_dynamic_payoff_map,
        )

        # Test with no ticker (fallback mode)
        payoff_map = get_dynamic_payoff_map(None, "SPECULATIVE_CRYPTO_BIO")

        # CRASH should be theory-based (-60%), not default (-25%)
        assert payoff_map["CRASH"] == CRASH_IMPACT_MAP["SPECULATIVE_CRYPTO_BIO"]
        assert payoff_map["CRASH"] == -0.60

    def test_volatility_floor_applied(self):
        """Very low volatility should be floored at 8%."""
        from src.workflow.nodes.debate.market_data import VOLATILITY_FLOOR

        assert VOLATILITY_FLOOR == 0.08

    @patch("src.workflow.nodes.debate.market_data.yf.download")
    def test_fallback_on_download_failure(self, mock_download):
        """Should return default map with theory-based crash on failure."""
        from src.workflow.nodes.debate.market_data import get_dynamic_payoff_map

        mock_download.return_value = pd.DataFrame()  # Empty data

        payoff_map = get_dynamic_payoff_map("INVALID", "GROWTH_TECH")

        # Should use defaults for upside
        assert payoff_map["SURGE"] == 0.25
        assert payoff_map["MODERATE_UP"] == 0.10

        # But CRASH should still be theory-based
        assert payoff_map["CRASH"] == -0.35
