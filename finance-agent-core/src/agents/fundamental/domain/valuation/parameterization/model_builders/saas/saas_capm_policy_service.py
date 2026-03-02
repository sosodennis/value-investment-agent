from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from src.shared.kernel.traceable import ManualProvenance, TraceableField

from ....policies.manual_assumption_policy import DEFAULT_TERMINAL_GROWTH
from ..shared.capm_market_defaults_service import resolve_capm_market_defaults

DEFAULT_SAAS_RISK_FREE_RATE = 0.042
DEFAULT_SAAS_BETA = 1.0
WACC_FLOOR = 0.05
WACC_CEILING = 0.30
TERMINAL_GROWTH_FLOOR = -0.02
TERMINAL_GROWTH_CEILING = 0.04
TERMINAL_GROWTH_SPREAD_BUFFER = 0.005


@dataclass(frozen=True)
class SaasCapmTerminalInputs:
    risk_free_rate: float
    beta: float
    market_risk_premium: float
    wacc_tf: TraceableField[float]
    terminal_growth_tf: TraceableField[float]


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def build_saas_capm_terminal_inputs(
    *,
    market_snapshot: Mapping[str, object] | None,
    market_float: Callable[[Mapping[str, object] | None, str], float | None],
    default_market_risk_premium: float,
    assumptions: list[str],
) -> SaasCapmTerminalInputs:
    market_defaults = resolve_capm_market_defaults(
        market_snapshot=market_snapshot,
        market_float=market_float,
        default_risk_free_rate=DEFAULT_SAAS_RISK_FREE_RATE,
        risk_free_format=".2%",
        default_beta=DEFAULT_SAAS_BETA,
        beta_format=".2f",
        default_market_risk_premium=default_market_risk_premium,
        market_risk_premium_format=".2%",
        assumptions=assumptions,
    )
    risk_free_rate = market_defaults.risk_free_rate
    beta = market_defaults.beta
    market_risk_premium = market_defaults.market_risk_premium

    raw_wacc = risk_free_rate + (beta * market_risk_premium)
    clamped_wacc = _clamp(raw_wacc, WACC_FLOOR, WACC_CEILING)
    if clamped_wacc != raw_wacc:
        assumptions.append(
            f"wacc clamped from {raw_wacc:.2%} to {clamped_wacc:.2%} "
            f"(bounds={WACC_FLOOR:.2%}-{WACC_CEILING:.2%})"
        )
    else:
        assumptions.append("wacc sourced from market-aware CAPM inputs")
    wacc_tf = TraceableField(
        name="WACC",
        value=clamped_wacc,
        provenance=ManualProvenance(
            description=(
                "Market-aware CAPM-derived WACC: "
                f"risk_free_rate + beta * market_risk_premium = {raw_wacc:.4f}"
            ),
            author="ValuationPolicy",
        ),
    )

    consensus_growth_rate = market_float(market_snapshot, "consensus_growth_rate")
    terminal_candidate = (
        consensus_growth_rate
        if consensus_growth_rate is not None
        else DEFAULT_TERMINAL_GROWTH
    )
    terminal_upper_bound = min(
        TERMINAL_GROWTH_CEILING,
        clamped_wacc - TERMINAL_GROWTH_SPREAD_BUFFER,
    )
    if terminal_upper_bound <= TERMINAL_GROWTH_FLOOR:
        terminal_upper_bound = TERMINAL_GROWTH_FLOOR + 0.001
    clamped_terminal_growth = _clamp(
        terminal_candidate,
        TERMINAL_GROWTH_FLOOR,
        terminal_upper_bound,
    )
    if consensus_growth_rate is None:
        assumptions.append(
            f"terminal_growth defaulted to {DEFAULT_TERMINAL_GROWTH:.2%} "
            "(consensus unavailable)"
        )
    elif clamped_terminal_growth != terminal_candidate:
        assumptions.append(
            f"terminal_growth clamped from {terminal_candidate:.2%} to "
            f"{clamped_terminal_growth:.2%} "
            f"(bounds={TERMINAL_GROWTH_FLOOR:.2%}-{terminal_upper_bound:.2%})"
        )
    else:
        assumptions.append("terminal_growth sourced from consensus_growth_rate")
    terminal_growth_tf = TraceableField(
        name="Terminal Growth",
        value=clamped_terminal_growth,
        provenance=ManualProvenance(
            description=(
                "Consensus-aware terminal growth with economic bounds "
                f"(upper=min({TERMINAL_GROWTH_CEILING:.2%}, wacc-"
                f"{TERMINAL_GROWTH_SPREAD_BUFFER:.2%}))"
            ),
            author="ValuationPolicy",
        ),
    )

    return SaasCapmTerminalInputs(
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
        wacc_tf=wacc_tf,
        terminal_growth_tf=terminal_growth_tf,
    )
