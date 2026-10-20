"""Stable public contracts and services for technical verification."""

from .application.verification_runtime_service import (
    VerificationRuntimeRequest,
    VerificationRuntimeResult,
    VerificationRuntimeService,
)
from .domain.baseline_gate_policy import (
    VerificationBaselineThresholds,
    VerificationGateIssue,
    VerificationGateResult,
    evaluate_verification_baseline,
)
from .domain.contracts import (
    BacktestResult,
    BacktestResults,
    BacktestSummary,
    WalkForwardResult,
    WfaSummary,
)

__all__ = [
    "BacktestResult",
    "BacktestResults",
    "BacktestSummary",
    "VerificationBaselineThresholds",
    "VerificationGateIssue",
    "VerificationGateResult",
    "VerificationRuntimeRequest",
    "VerificationRuntimeResult",
    "VerificationRuntimeService",
    "WalkForwardResult",
    "WfaSummary",
    "evaluate_verification_baseline",
]
