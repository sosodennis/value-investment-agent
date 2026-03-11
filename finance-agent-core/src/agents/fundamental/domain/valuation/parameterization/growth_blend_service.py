from __future__ import annotations

from collections.abc import Mapping

from src.shared.kernel.traceable import (
    ManualProvenance,
    TraceableField,
)

from ..policies.growth_assumption_policy import (
    blend_growth_rate,
    build_linear_decay_weights,
    project_growth_rate_series,
)
from .series_service import (
    computed_field,
    growth_observations_from_series,
    growth_rates_from_series,
    population_stddev,
)
from .snapshot_service import market_float, market_mapping

HISTORICAL_SHORT_WINDOW = 3
HISTORICAL_LONG_WINDOW = 5
HISTORICAL_SHORT_WEIGHT = 0.60
HISTORICAL_LONG_WEIGHT = 0.40
HISTORICAL_GROWTH_CLIP_MIN = -0.40
HISTORICAL_GROWTH_CLIP_MAX = 0.80
_LONG_HORIZON_GROWTH_HORIZONS = {"long_term", "multi_year"}
_SHORT_HORIZON_GROWTH_HORIZONS = {"short_term"}
_MIN_GROWTH_SERIES_VALUE = -0.50
_MAX_GROWTH_SERIES_VALUE = 1.20
_LONG_HORIZON_DCF_PROJECTION_YEARS = 10
_LOW_PREMIUM_DEGRADED_CONSENSUS_PREMIUM_THRESHOLD = 0.30
_LOW_PREMIUM_DEGRADED_CONSENSUS_DECAY_DAMPING_FACTOR = 0.35


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return float(normalized)
        except ValueError:
            return None
    return None


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return int(float(normalized))
        except ValueError:
            return None
    return None


def _resolve_low_premium_degraded_consensus_damping(
    *,
    market_snapshot: Mapping[str, object] | None,
) -> tuple[float | None, float | None, str | None]:
    if market_snapshot is None:
        return None, None, None
    current_price = market_float(market_snapshot, "current_price")
    target_mean_price = market_float(market_snapshot, "target_mean_price")
    if (
        current_price is None
        or current_price <= 0
        or target_mean_price is None
        or target_mean_price <= 0
    ):
        return None, None, None
    premium = (target_mean_price / current_price) - 1.0
    if premium > _LOW_PREMIUM_DEGRADED_CONSENSUS_PREMIUM_THRESHOLD:
        return None, premium, None

    fallback_reason_raw = market_snapshot.get("target_consensus_fallback_reason")
    fallback_reason = (
        fallback_reason_raw
        if isinstance(fallback_reason_raw, str) and fallback_reason_raw.strip()
        else None
    )
    quality_bucket_raw = market_snapshot.get("target_consensus_quality_bucket")
    quality_bucket = (
        quality_bucket_raw.strip().lower()
        if isinstance(quality_bucket_raw, str) and quality_bucket_raw.strip()
        else None
    )
    is_degraded = fallback_reason is not None or quality_bucket == "degraded"
    if not is_degraded:
        return None, premium, None
    return (
        _LOW_PREMIUM_DEGRADED_CONSENSUS_DECAY_DAMPING_FACTOR,
        premium,
        fallback_reason,
    )


def _clip_growth_observations(values: list[float]) -> tuple[list[float], int]:
    clipped: list[float] = []
    clip_count = 0
    for raw in values:
        bounded = max(HISTORICAL_GROWTH_CLIP_MIN, min(HISTORICAL_GROWTH_CLIP_MAX, raw))
        if bounded != raw:
            clip_count += 1
        clipped.append(bounded)
    return clipped, clip_count


def _average_window(values: list[float], window: int) -> float | None:
    if not values:
        return None
    if window <= 0:
        return None
    windowed = values[:window]
    if not windowed:
        return None
    return sum(windowed) / len(windowed)


def _resolve_blended_historical_growth(
    observations: list[float],
) -> tuple[float | None, float | None, float | None, int]:
    clipped, clip_count = _clip_growth_observations(observations)
    short_anchor = _average_window(clipped, HISTORICAL_SHORT_WINDOW)
    long_anchor = _average_window(clipped, HISTORICAL_LONG_WINDOW)

    if short_anchor is not None and long_anchor is not None:
        blended = (short_anchor * HISTORICAL_SHORT_WEIGHT) + (
            long_anchor * HISTORICAL_LONG_WEIGHT
        )
        return blended, short_anchor, long_anchor, clip_count
    if short_anchor is not None:
        return short_anchor, short_anchor, long_anchor, clip_count
    if long_anchor is not None:
        return long_anchor, short_anchor, long_anchor, clip_count
    return None, short_anchor, long_anchor, clip_count


def _extract_consensus_growth_signal(
    *,
    market_snapshot: Mapping[str, object] | None,
    assumptions: list[str],
) -> tuple[float | None, str | None, str]:
    consensus_growth = market_float(market_snapshot, "consensus_growth_rate")
    if consensus_growth is None:
        return None, None, "none"

    market_datums = market_mapping(market_snapshot, "market_datums")
    if market_datums is None:
        assumptions.append(
            "consensus_growth_rate horizon metadata missing; treated as long-horizon "
            "for compatibility"
        )
        return consensus_growth, "unknown", "compatibility_assumed"

    consensus_datum = market_datums.get("consensus_growth_rate")
    if not isinstance(consensus_datum, Mapping):
        assumptions.append(
            "consensus_growth_rate market datum missing; treated as long-horizon "
            "for compatibility"
        )
        return consensus_growth, "unknown", "compatibility_assumed"

    horizon_raw = consensus_datum.get("horizon")
    if not isinstance(horizon_raw, str) or not horizon_raw:
        assumptions.append(
            "consensus_growth_rate horizon unknown; treated as long-horizon "
            "for compatibility"
        )
        return consensus_growth, "unknown", "compatibility_assumed"
    horizon = horizon_raw.strip().lower()
    if horizon not in _LONG_HORIZON_GROWTH_HORIZONS:
        if horizon in _SHORT_HORIZON_GROWTH_HORIZONS:
            return consensus_growth, horizon, "short_term_decayed"
        assumptions.append(
            "consensus_growth_rate ignored for long-horizon DCF growth blend "
            f"(horizon={horizon})"
        )
        return None, horizon, "ignored"

    assumptions.append(
        "consensus_growth_rate included in long-horizon DCF growth blend "
        f"(horizon={horizon})"
    )
    return consensus_growth, horizon, "included"


def _clamp_growth_rate(value: float) -> float:
    return max(_MIN_GROWTH_SERIES_VALUE, min(_MAX_GROWTH_SERIES_VALUE, value))


def build_saas_growth_rates(
    *,
    revenue_series: list[TraceableField[float]],
    market_snapshot: Mapping[str, object] | None,
    assumptions: list[str],
    projection_years: int,
    long_run_target: float,
    high_growth_trigger: float,
    short_term_consensus_decay_years: int,
) -> TraceableField[list[float]]:
    historical_growth_tf = growth_rates_from_series(
        "Revenue Growth Rates (Historical Baseline)",
        revenue_series,
        projection_years,
    )

    historical_observations = growth_observations_from_series(revenue_series)
    (
        historical_growth,
        short_anchor,
        long_anchor,
        clipped_observation_count,
    ) = _resolve_blended_historical_growth(historical_observations)
    clipped_observations, _ = _clip_growth_observations(historical_observations)
    historical_volatility = population_stddev(clipped_observations)
    if historical_growth is None and historical_growth_tf.value:
        historical_growth = float(historical_growth_tf.value[0])
        assumptions.append(
            "historical_growth_anchor fallback to full-history average YoY "
            "(insufficient short/long window observations)"
        )
    elif historical_growth is not None:
        assumptions.append(
            "historical_growth_anchor blended from clipped YoY windows "
            f"(short={HISTORICAL_SHORT_WINDOW}, long={HISTORICAL_LONG_WINDOW}, "
            f"weights={HISTORICAL_SHORT_WEIGHT:.2f}/{HISTORICAL_LONG_WEIGHT:.2f}, "
            f"observations={len(historical_observations)}, "
            f"clipped_observations={clipped_observation_count})"
        )
    (
        consensus_growth,
        consensus_horizon,
        consensus_policy,
    ) = _extract_consensus_growth_signal(
        market_snapshot=market_snapshot,
        assumptions=assumptions,
    )
    consensus_growth_for_blend = (
        consensus_growth
        if consensus_policy in {"included", "compatibility_assumed"}
        else None
    )

    blend_result = blend_growth_rate(
        historical_growth=historical_growth,
        consensus_growth=consensus_growth_for_blend,
        historical_volatility=historical_volatility,
    )
    if blend_result is None:
        return historical_growth_tf

    blended_series = project_growth_rate_series(
        base_growth=blend_result.blended_growth,
        projection_years=projection_years,
        long_run_target=long_run_target,
        high_growth_trigger=high_growth_trigger,
    )
    expression = blend_result.rationale
    if (
        consensus_policy == "short_term_decayed"
        and consensus_growth is not None
        and short_term_consensus_decay_years > 0
    ):
        resolved_decay_years = short_term_consensus_decay_years
        if (
            projection_years >= _LONG_HORIZON_DCF_PROJECTION_YEARS
            and blend_result.weights.profile == "mature_stable"
        ):
            # Extend mature-profile short-term consensus influence for long DCF horizon.
            resolved_decay_years += 5
        decay_window = min(resolved_decay_years, len(blended_series))
        decay_weights = build_linear_decay_weights(decay_window)
        anchor_growth = blend_result.blended_growth
        delta = consensus_growth - anchor_growth
        (
            damping_factor,
            target_premium,
            fallback_reason,
        ) = _resolve_low_premium_degraded_consensus_damping(
            market_snapshot=market_snapshot
        )
        if damping_factor is not None:
            delta *= damping_factor
            assumptions.append(
                "consensus_growth_rate decay amplitude damped for low-premium degraded consensus "
                f"(target_premium={target_premium:.2%}, damping_factor={damping_factor:.2f}, "
                f"fallback_reason={fallback_reason or 'none'})"
            )
        adjusted_series = list(blended_series)
        for idx, weight in enumerate(decay_weights):
            adjusted_series[idx] = _clamp_growth_rate(
                adjusted_series[idx] + (delta * weight)
            )
        blended_series = adjusted_series
        weights_label = "|".join(f"{weight:.2f}" for weight in decay_weights)
        assumptions.append(
            "consensus_growth_rate decayed into near-term DCF growth path "
            f"(horizon={consensus_horizon or 'short_term'}, "
            f"window_years={decay_window}, weights={weights_label})"
        )
        expression = (
            f"{expression}; short_term_consensus_decay("
            f"window_years={decay_window}, weights={weights_label})"
        )
    elif (
        consensus_policy == "short_term_decayed"
        and short_term_consensus_decay_years <= 0
    ):
        assumptions.append(
            "consensus_growth_rate short-term decay disabled; ignored for DCF growth blend "
            f"(horizon={consensus_horizon or 'short_term'}, "
            f"window_years={short_term_consensus_decay_years})"
        )

    blend_inputs: dict[str, TraceableField] = {}
    if historical_growth is not None:
        historical_anchor_tf = TraceableField(
            name="Historical Revenue Growth Anchor",
            value=historical_growth,
            provenance=ManualProvenance(
                description=(
                    "Blended historical growth anchor from clipped YoY windows "
                    f"(short={HISTORICAL_SHORT_WINDOW}, long={HISTORICAL_LONG_WINDOW}, "
                    f"short_anchor={short_anchor}, long_anchor={long_anchor})"
                ),
                author="ValuationPolicy",
            ),
        )
        blend_inputs["historical_growth"] = historical_anchor_tf
    if consensus_growth is not None:
        provider_raw = (
            None if market_snapshot is None else market_snapshot.get("provider")
        )
        provider = provider_raw if isinstance(provider_raw, str) else "market_data"
        consensus_tf = TraceableField(
            name="Consensus Revenue Growth",
            value=consensus_growth,
            provenance=ManualProvenance(
                description=f"Consensus growth from market data provider={provider}",
                author="MarketDataService",
            ),
        )
        blend_inputs["consensus_growth"] = consensus_tf

    assumptions.append(
        "growth_rates blended via context-aware weights "
        f"(profile={blend_result.weights.profile})"
        + (
            " using historical growth and long-horizon consensus signals"
            if consensus_growth_for_blend is not None
            else (
                " using historical growth with decayed short-term consensus overlay"
                if consensus_policy == "short_term_decayed"
                and consensus_growth is not None
                and short_term_consensus_decay_years > 0
                else " using historical growth signals only"
            )
        )
    )

    return computed_field(
        name="Revenue Growth Rates",
        value=blended_series,
        op_code="GROWTH_BLEND",
        expression=expression,
        inputs=blend_inputs,
    )
