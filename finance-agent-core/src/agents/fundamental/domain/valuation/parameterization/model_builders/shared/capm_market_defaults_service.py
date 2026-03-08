from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class CapmMarketDefaults:
    risk_free_rate: float
    beta: float
    market_risk_premium: float


def resolve_capm_market_defaults(
    *,
    market_snapshot: Mapping[str, object] | None,
    market_float: Callable[[Mapping[str, object] | None, str], float | None],
    default_risk_free_rate: float,
    risk_free_format: str,
    default_beta: float,
    beta_format: str,
    default_market_risk_premium: float,
    market_risk_premium_format: str,
    allow_market_snapshot_mrp: bool,
    assumptions: list[str],
) -> CapmMarketDefaults:
    risk_free_rate = market_float(market_snapshot, "risk_free_rate")
    if risk_free_rate is None:
        risk_free_rate = default_risk_free_rate
        assumptions.append(
            f"risk_free_rate defaulted to {default_risk_free_rate:{risk_free_format}}"
        )

    beta = market_float(market_snapshot, "beta")
    if beta is None:
        beta = default_beta
        assumptions.append(f"beta defaulted to {default_beta:{beta_format}}")

    snapshot_market_risk_premium = market_float(market_snapshot, "market_risk_premium")
    if allow_market_snapshot_mrp and snapshot_market_risk_premium is not None:
        market_risk_premium = snapshot_market_risk_premium
        assumptions.append("market_risk_premium sourced from market snapshot")
    else:
        market_risk_premium = default_market_risk_premium
        assumptions.append(
            "market_risk_premium defaulted to "
            f"{default_market_risk_premium:{market_risk_premium_format}}"
        )
        if snapshot_market_risk_premium is not None:
            assumptions.append(
                "market_risk_premium from market snapshot ignored by policy "
                "(market-level source only)"
            )

    return CapmMarketDefaults(
        risk_free_rate=risk_free_rate,
        beta=beta,
        market_risk_premium=market_risk_premium,
    )
