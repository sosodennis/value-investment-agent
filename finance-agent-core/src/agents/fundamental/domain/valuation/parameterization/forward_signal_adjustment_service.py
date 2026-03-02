from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from src.shared.kernel.types import JSONObject

from ..policies.forward_signal_policy import apply_forward_signal_policy
from .forward_signal_parser_service import parse_market_forward_signals
from .snapshot_service import merge_metadata


@dataclass(frozen=True)
class ForwardSignalAdjustmentOutcome:
    params: dict[str, object]
    assumptions: list[str]
    metadata: JSONObject
    log_fields: JSONObject | None


def apply_forward_signal_adjustments(
    *,
    params: Mapping[str, object],
    assumptions: list[str],
    metadata: JSONObject,
    model_type: str,
    raw_signals: object,
) -> ForwardSignalAdjustmentOutcome:
    signals = parse_market_forward_signals(raw_signals)
    policy = apply_forward_signal_policy(signals)
    updated_assumptions = list(assumptions)
    updated_params = dict(params)
    updated_metadata = merge_metadata(
        metadata,
        {"forward_signal": policy.to_summary()},
    )

    if policy.total_count == 0:
        updated_assumptions.append(
            "forward_signals provided but none passed schema validation"
        )
        return ForwardSignalAdjustmentOutcome(
            params=updated_params,
            assumptions=updated_assumptions,
            metadata=updated_metadata,
            log_fields=None,
        )

    updated_assumptions.append(
        "forward_signals processed "
        f"(accepted={policy.accepted_count}, rejected={policy.rejected_count})"
    )
    if policy.risk_level == "high":
        updated_assumptions.append(
            "high-risk: low-confidence forward signal(s) down-weighted by policy"
        )

    growth_applied = apply_series_adjustment(
        params=updated_params,
        field_names=("growth_rates", "income_growth_rates"),
        adjustment=policy.growth_adjustment,
        min_bound=-0.80,
        max_bound=1.50,
    )
    if growth_applied and abs(policy.growth_adjustment_basis_points) > 1e-9:
        updated_assumptions.append(
            "forward_signal growth adjustment applied "
            f"({policy.growth_adjustment_basis_points:+.1f} basis points)"
        )

    margin_applied = apply_series_adjustment(
        params=updated_params,
        field_names=("operating_margins",),
        adjustment=policy.margin_adjustment,
        min_bound=-0.50,
        max_bound=0.70,
    )
    if margin_applied and abs(policy.margin_adjustment_basis_points) > 1e-9:
        updated_assumptions.append(
            "forward_signal margin adjustment applied "
            f"({policy.margin_adjustment_basis_points:+.1f} basis points)"
        )

    if (
        not growth_applied
        and abs(policy.growth_adjustment_basis_points) > 1e-9
        and model_type in {"saas", "dcf_standard", "dcf_growth", "bank"}
    ):
        updated_assumptions.append(
            "forward_signal growth adjustment computed but no compatible growth series found"
        )
    if (
        not margin_applied
        and abs(policy.margin_adjustment_basis_points) > 1e-9
        and model_type in {"saas", "dcf_standard", "dcf_growth"}
    ):
        updated_assumptions.append(
            "forward_signal margin adjustment computed but no compatible margin series found"
        )

    log_fields: JSONObject = {
        "model_type": model_type,
        "signals_total": policy.total_count,
        "signals_accepted": policy.accepted_count,
        "signals_rejected": policy.rejected_count,
        "growth_adjustment_basis_points": policy.growth_adjustment_basis_points,
        "margin_adjustment_basis_points": policy.margin_adjustment_basis_points,
        "risk_level": policy.risk_level,
        "growth_applied": growth_applied,
        "margin_applied": margin_applied,
    }
    return ForwardSignalAdjustmentOutcome(
        params=updated_params,
        assumptions=updated_assumptions,
        metadata=updated_metadata,
        log_fields=log_fields,
    )


def apply_series_adjustment(
    *,
    params: dict[str, object],
    field_names: tuple[str, ...],
    adjustment: float,
    min_bound: float,
    max_bound: float,
) -> bool:
    if abs(adjustment) <= 1e-12:
        return False

    for field_name in field_names:
        raw_series = params.get(field_name)
        if not isinstance(raw_series, list | tuple):
            continue
        adjusted: list[float] = []
        valid = True
        for value in raw_series:
            if not isinstance(value, int | float) or isinstance(value, bool):
                valid = False
                break
            shifted = float(value) + adjustment
            adjusted.append(max(min_bound, min(max_bound, shifted)))
        if not valid or not adjusted:
            continue
        params[field_name] = adjusted
        return True
    return False


__all__ = [
    "ForwardSignalAdjustmentOutcome",
    "apply_forward_signal_adjustments",
    "apply_series_adjustment",
]
