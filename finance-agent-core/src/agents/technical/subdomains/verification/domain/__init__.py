"""verification.domain package."""

from .baseline_gate_policy import (
    VerificationBaselineThresholds,
    VerificationGateIssue,
    VerificationGateResult,
    evaluate_verification_baseline,
)
from .contracts import (
    BacktestResult,
    BacktestResults,
    BacktestSummary,
    WalkForwardResult,
    WfaSummary,
)
from .engine_service import CombinedBacktester
from .walk_forward_service import WalkForwardOptimizer

__all__ = [
    "BacktestResult",
    "BacktestResults",
    "BacktestSummary",
    "WalkForwardResult",
    "WfaSummary",
    "CombinedBacktester",
    "WalkForwardOptimizer",
    "VerificationBaselineThresholds",
    "VerificationGateIssue",
    "VerificationGateResult",
    "evaluate_verification_baseline",
]
