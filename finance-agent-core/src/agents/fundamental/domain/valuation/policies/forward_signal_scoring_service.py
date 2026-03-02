from __future__ import annotations

from typing import Literal

from .forward_signal_contracts import (
    DEFAULT_FORWARD_SIGNAL_CONFIDENCE_THRESHOLD,
    DEFAULT_FORWARD_SIGNAL_MAX_ADJUSTMENT_BASIS_POINTS,
    ForwardSignal,
    ForwardSignalDecision,
    ForwardSignalPolicyResult,
)

_SUPPORTED_V1_POLICY_METRICS = {"growth_outlook", "margin_outlook"}


def apply_forward_signal_policy(
    signals: tuple[ForwardSignal, ...],
    *,
    confidence_threshold: float = DEFAULT_FORWARD_SIGNAL_CONFIDENCE_THRESHOLD,
    max_adjustment_basis_points: float = (
        DEFAULT_FORWARD_SIGNAL_MAX_ADJUSTMENT_BASIS_POINTS
    ),
) -> ForwardSignalPolicyResult:
    decisions: list[ForwardSignalDecision] = []
    weighted_basis_points: dict[str, float] = {
        "growth_outlook": 0.0,
        "margin_outlook": 0.0,
    }
    weights: dict[str, float] = {"growth_outlook": 0.0, "margin_outlook": 0.0}
    evidence_count = 0

    for signal in signals:
        evidence_count += len(signal.evidence)
        metric = signal.metric
        if metric not in _SUPPORTED_V1_POLICY_METRICS:
            decisions.append(
                ForwardSignalDecision(
                    signal_id=signal.signal_id,
                    metric=metric,
                    accepted=False,
                    reason="unsupported_metric_for_v1",
                    effective_basis_points=0.0,
                    risk_tag=None,
                )
            )
            continue

        if len(signal.evidence) == 0:
            decisions.append(
                ForwardSignalDecision(
                    signal_id=signal.signal_id,
                    metric=metric,
                    accepted=False,
                    reason="missing_evidence",
                    effective_basis_points=0.0,
                    risk_tag="high_risk",
                )
            )
            continue

        signed_basis_points = _signed_signal_basis_points(signal)
        confidence = _clamp(signal.confidence, 0.0, 1.0)
        risk_tag: str | None = None
        weight = confidence
        if confidence < confidence_threshold:
            risk_tag = "low_confidence"
            weight = confidence * 0.25

        if weight <= 0.0:
            decisions.append(
                ForwardSignalDecision(
                    signal_id=signal.signal_id,
                    metric=metric,
                    accepted=False,
                    reason="zero_weight_after_policy",
                    effective_basis_points=0.0,
                    risk_tag=risk_tag,
                )
            )
            continue

        weighted_basis_points[metric] += signed_basis_points * weight
        weights[metric] += weight
        decisions.append(
            ForwardSignalDecision(
                signal_id=signal.signal_id,
                metric=metric,
                accepted=True,
                reason="accepted",
                effective_basis_points=signed_basis_points,
                risk_tag=risk_tag,
            )
        )

    growth_basis_points = 0.0
    margin_basis_points = 0.0
    if weights["growth_outlook"] > 0.0:
        growth_basis_points = (
            weighted_basis_points["growth_outlook"] / weights["growth_outlook"]
        )
    if weights["margin_outlook"] > 0.0:
        margin_basis_points = (
            weighted_basis_points["margin_outlook"] / weights["margin_outlook"]
        )

    growth_basis_points = _clamp(
        growth_basis_points,
        -max_adjustment_basis_points,
        max_adjustment_basis_points,
    )
    margin_basis_points = _clamp(
        margin_basis_points,
        -max_adjustment_basis_points,
        max_adjustment_basis_points,
    )

    accepted_count = sum(1 for item in decisions if item.accepted)
    rejected_count = len(decisions) - accepted_count
    has_low_confidence = any(
        item.accepted and item.risk_tag == "low_confidence" for item in decisions
    )
    source_types = tuple(
        sorted({signal.source_type for signal in signals if signal.source_type})
    )
    if len(decisions) == 0:
        risk_level: Literal["low", "medium", "high"] = "low"
    elif has_low_confidence:
        risk_level = "high"
    elif rejected_count > 0:
        risk_level = "medium"
    else:
        risk_level = "low"

    return ForwardSignalPolicyResult(
        total_count=len(decisions),
        accepted_count=accepted_count,
        rejected_count=rejected_count,
        evidence_count=evidence_count,
        growth_adjustment=growth_basis_points / 10_000.0,
        margin_adjustment=margin_basis_points / 10_000.0,
        growth_adjustment_basis_points=growth_basis_points,
        margin_adjustment_basis_points=margin_basis_points,
        risk_level=risk_level,
        source_types=source_types,
        decisions=tuple(decisions),
    )


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _signed_signal_basis_points(signal: ForwardSignal) -> float:
    raw_basis_points = (
        signal.value * 10_000.0 if signal.unit == "ratio" else signal.value
    )
    magnitude = abs(raw_basis_points)
    if signal.direction == "down":
        return -magnitude
    if signal.direction == "neutral":
        return 0.0
    return magnitude
