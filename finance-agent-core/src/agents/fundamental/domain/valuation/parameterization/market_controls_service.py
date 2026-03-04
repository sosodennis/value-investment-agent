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

DEFAULT_MARKET_STALE_MAX_DAYS = 5


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
        assumptions.append("shares_outstanding fallback to filing (market unavailable)")
        return filing_shares_tf

    stale_max_days = _resolve_market_stale_max_days(market_snapshot)
    is_stale, stale_days = _extract_market_share_staleness(market_snapshot)
    if is_stale is True:
        assumptions.append(
            "shares_outstanding fallback to filing "
            f"(market stale: age_days={stale_days}, threshold={stale_max_days})"
        )
        return filing_shares_tf

    provider_raw = None if market_snapshot is None else market_snapshot.get("provider")
    as_of_raw = None if market_snapshot is None else market_snapshot.get("as_of")
    provider = str(provider_raw) if isinstance(provider_raw, str) else "market_data"
    as_of = str(as_of_raw) if isinstance(as_of_raw, str) else "unknown"

    assumptions.append(
        "shares_outstanding sourced from market data "
        f"(stale={is_stale}, age_days={stale_days}, threshold={stale_max_days})"
    )
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


def _resolve_market_stale_max_days(
    market_snapshot: Mapping[str, object] | None,
) -> int:
    configured = env_int(
        "FUNDAMENTAL_MARKET_STALE_MAX_DAYS",
        DEFAULT_MARKET_STALE_MAX_DAYS,
        minimum=0,
    )
    if market_snapshot is None:
        return configured
    snapshot_value = to_int(market_snapshot.get("market_stale_max_days"))
    if snapshot_value is None or snapshot_value < 0:
        return configured
    return snapshot_value


def _extract_market_share_staleness(
    market_snapshot: Mapping[str, object] | None,
) -> tuple[bool | None, int | None]:
    if market_snapshot is None:
        return None, None

    snapshot_is_stale = market_snapshot.get("shares_outstanding_is_stale")
    snapshot_days = market_snapshot.get("shares_outstanding_staleness_days")
    is_stale = snapshot_is_stale if isinstance(snapshot_is_stale, bool) else None
    stale_days = snapshot_days if isinstance(snapshot_days, int) else None
    if is_stale is not None:
        return is_stale, stale_days

    market_datums_raw = market_snapshot.get("market_datums")
    if not isinstance(market_datums_raw, Mapping):
        return None, None
    shares_datum_raw = market_datums_raw.get("shares_outstanding")
    if not isinstance(shares_datum_raw, Mapping):
        return None, None
    staleness_raw = shares_datum_raw.get("staleness")
    if not isinstance(staleness_raw, Mapping):
        return None, None
    datum_is_stale = staleness_raw.get("is_stale")
    datum_days = staleness_raw.get("days")
    return (
        datum_is_stale if isinstance(datum_is_stale, bool) else None,
        datum_days if isinstance(datum_days, int) else None,
    )
