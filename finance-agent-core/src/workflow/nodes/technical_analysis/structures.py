"""
Data structures for Technical Analysis node.

Defines schemas for FracDiff metrics, signal states, and output formats.
"""

from enum import Enum

from pydantic import BaseModel, Field


class MemoryStrength(str, Enum):
    """Classification of memory strength based on optimal d value."""

    STRUCTURALLY_STABLE = "structurally_stable"  # d < 0.3
    BALANCED = "balanced"  # 0.3 <= d <= 0.6
    FRAGILE = "fragile"  # d > 0.6


class StatisticalState(str, Enum):
    """Classification of statistical state based on Z-score."""

    EQUILIBRIUM = "equilibrium"  # |Z| < 1.0
    DEVIATING = "deviating"  # 1.0 <= |Z| < 2.0
    STATISTICAL_ANOMALY = "anomaly"  # |Z| >= 2.0


class RiskLevel(str, Enum):
    """Risk level classification."""

    LOW = "low"
    MEDIUM = "medium"
    CRITICAL = "critical"


class FracDiffMetrics(BaseModel):
    """Fractional differentiation metrics."""

    optimal_d: float = Field(
        ..., description="Optimal fractional differentiation order"
    )
    window_length: int = Field(
        ..., description="Required window length for FracDiff computation"
    )
    adf_statistic: float = Field(..., description="ADF test statistic")
    adf_pvalue: float = Field(..., description="ADF test p-value")
    memory_strength: MemoryStrength = Field(
        ..., description="Classification of memory strength"
    )


class ConfluenceEvidence(BaseModel):
    """Container for multi-indicator confluence evidence."""

    bollinger_state: str = Field(
        ..., description="Bollinger band state (INSIDE, BREAKOUT_UPPER, BREAKOUT_LOWER)"
    )
    rsi_score: float = Field(..., description="FD-RSI Type B score (0-100)")
    macd_momentum: str = Field(..., description="MACD momentum state")
    obv_state: str = Field(..., description="FD-OBV volume flow state")


class SignalState(BaseModel):
    """Current signal state from FracDiff analysis."""

    z_score: float = Field(
        ..., description="Z-score of current FracDiff value vs historical distribution"
    )
    statistical_state: StatisticalState = Field(
        ..., description="Classification of statistical state"
    )
    direction: str = Field(
        ..., description="Direction: BULLISH_EXTENSION or BEARISH_EXTENSION"
    )
    risk_level: RiskLevel = Field(..., description="Risk level classification")
    confluence: ConfluenceEvidence = Field(
        ..., description="Secondary indicator evidence"
    )


class TechnicalSignal(BaseModel):
    """Complete technical analysis signal output."""

    ticker: str = Field(..., description="Stock ticker symbol")
    timestamp: str = Field(..., description="Analysis timestamp (ISO format)")
    frac_diff_metrics: FracDiffMetrics = Field(
        ..., description="Fractional differentiation metrics"
    )
    signal_state: SignalState = Field(..., description="Current signal state")
    semantic_tags: list[str] = Field(
        ..., description="Deterministic semantic tags for LLM interpretation"
    )
    llm_interpretation: str | None = Field(
        None, description="LLM-generated interpretation of the signal"
    )
    raw_data: dict = Field(
        default_factory=dict, description="Raw data for debugging/verification"
    )
