from __future__ import annotations

from collections.abc import Mapping

from src.shared.kernel.traceable import (
    ManualProvenance,
    TraceableField,
)

from .snapshot_service import (
    env_bool,
    env_int,
    env_text,
    market_float,
    market_text,
    to_bool,
    to_int,
)
from .types import MonteCarloControls


def resolve_monte_carlo_controls(
    *,
    market_snapshot: Mapping[str, object] | None,
    assumptions: list[str],
    default_iterations: int,
    default_seed: int,
    default_sampler: str,
) -> MonteCarloControls:
    allowed_samplers = {"pseudo", "sobol", "lhs"}
    enabled = env_bool("FUNDAMENTAL_MONTE_CARLO_ENABLED", True)
    iterations = env_int(
        "FUNDAMENTAL_MONTE_CARLO_ITERATIONS",
        default_iterations,
        minimum=0,
    )
    seed = env_int(
        "FUNDAMENTAL_MONTE_CARLO_SEED",
        default_seed,
        minimum=0,
    )
    sampler = env_text("FUNDAMENTAL_MONTE_CARLO_SAMPLER", default_sampler)
    if sampler not in allowed_samplers:
        sampler = default_sampler

    if market_snapshot is not None:
        snapshot_enabled = to_bool(market_snapshot.get("monte_carlo_enabled"))
        snapshot_iterations = to_int(market_snapshot.get("monte_carlo_iterations"))
        snapshot_seed = to_int(market_snapshot.get("monte_carlo_seed"))
        snapshot_sampler_raw = market_text(market_snapshot, "monte_carlo_sampler")
        snapshot_sampler = (
            snapshot_sampler_raw.strip().lower()
            if isinstance(snapshot_sampler_raw, str)
            else None
        )
        if snapshot_enabled is not None:
            enabled = snapshot_enabled
        if snapshot_iterations is not None and snapshot_iterations >= 0:
            iterations = snapshot_iterations
        if snapshot_seed is not None and snapshot_seed >= 0:
            seed = snapshot_seed
        if snapshot_sampler in allowed_samplers:
            sampler = snapshot_sampler
        elif snapshot_sampler is not None:
            assumptions.append(
                "monte_carlo_sampler ignored invalid value "
                f"'{snapshot_sampler_raw}', fallback to {sampler}"
            )

    if not enabled:
        assumptions.append("monte_carlo disabled by policy")
        return 0, seed, sampler

    if iterations <= 0:
        assumptions.append("monte_carlo disabled (iterations <= 0)")
        return 0, seed, sampler

    enabled_statement = f"monte_carlo enabled with iterations={iterations}" + (
        f", seed={seed}" if seed is not None else ""
    )
    if sampler != default_sampler:
        enabled_statement += f", sampler={sampler}"
    assumptions.append(enabled_statement)
    return iterations, seed, sampler


def resolve_shares_outstanding(
    *,
    filing_shares_tf: TraceableField[float],
    market_snapshot: Mapping[str, object] | None,
    assumptions: list[str],
) -> TraceableField[float]:
    market_shares = market_float(market_snapshot, "shares_outstanding")
    if market_shares is None or market_shares <= 0:
        return filing_shares_tf

    provider_raw = None if market_snapshot is None else market_snapshot.get("provider")
    as_of_raw = None if market_snapshot is None else market_snapshot.get("as_of")
    provider = str(provider_raw) if isinstance(provider_raw, str) else "market_data"
    as_of = str(as_of_raw) if isinstance(as_of_raw, str) else "unknown"

    assumptions.append("shares_outstanding sourced from market data")
    return TraceableField(
        name="Shares Outstanding (Market)",
        value=market_shares,
        provenance=ManualProvenance(
            description=(
                "Latest shares outstanding from market data "
                f"(provider={provider}, as_of={as_of})"
            ),
            author="MarketDataService",
        ),
    )
