from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from statistics import median

from src.agents.fundamental.shared.contracts.traceable import (
    ManualProvenance,
    TraceableField,
)

from ....policies.base_assumption_guardrail_policy import (
    DEFAULT_BASE_ASSUMPTION_GUARDRAIL_VERSION,
    GrowthGuardrailConfig,
    MarginGuardrailConfig,
    ReinvestmentGuardrailConfig,
    apply_growth_guardrail,
    apply_margin_guardrail,
    apply_reinvestment_guardrail,
)
from ....report_contract import FinancialReport, IndustrialExtension
from ...reinvestment_clamp_profile_service import (
    ReinvestmentClampProfileLoadResult,
    load_reinvestment_clamp_profile,
)
from ..saas import SaasBuilderDeps, SaasBuildPayload, build_saas_payload


@dataclass(frozen=True)
class DCFVariantBuilderDeps:
    saas_deps: SaasBuilderDeps


@dataclass(frozen=True)
class _VariantGuardrailProfile:
    profile_name: str
    growth_config: GrowthGuardrailConfig
    margin_config: MarginGuardrailConfig
    capex_config: ReinvestmentGuardrailConfig
    wc_config: ReinvestmentGuardrailConfig
    terminal_growth_floor: float | None = None


_GUARDRAIL_PROFILE_VERSION = "shared_base_v2"

_BASE_GROWTH_GUARDRAIL = GrowthGuardrailConfig(
    max_year1_growth=0.49,
    max_series_growth=0.75,
    min_series_growth=-0.40,
    min_terminal_growth=0.00,
    max_terminal_growth=0.040,
    final_fade_years=4,
    enforce_nonincreasing_trend=True,
)
_BASE_MARGIN_GUARDRAIL = MarginGuardrailConfig(
    min_series_margin=-0.22,
    max_series_margin=0.59,
    normalized_margin_lower=0.15,
    normalized_margin_upper=0.38,
    final_fade_years=3,
)
_BASE_CAPEX_GUARDRAIL = ReinvestmentGuardrailConfig(
    min_series_rate=0.00,
    max_series_rate=0.28,
    terminal_lower=0.03,
    terminal_upper=0.10,
    final_fade_years=5,
)
_BASE_WC_GUARDRAIL = ReinvestmentGuardrailConfig(
    min_series_rate=-0.07,
    max_series_rate=0.12,
    terminal_lower=-0.02,
    terminal_upper=0.045,
    final_fade_years=5,
)


def _growth_config_from_base(
    *,
    max_year1_growth: float | None = None,
    max_series_growth: float | None = None,
    min_series_growth: float | None = None,
    min_terminal_growth: float | None = None,
    max_terminal_growth: float | None = None,
    final_fade_years: int | None = None,
    enforce_nonincreasing_trend: bool | None = None,
) -> GrowthGuardrailConfig:
    return GrowthGuardrailConfig(
        max_year1_growth=(
            _BASE_GROWTH_GUARDRAIL.max_year1_growth
            if max_year1_growth is None
            else max_year1_growth
        ),
        max_series_growth=(
            _BASE_GROWTH_GUARDRAIL.max_series_growth
            if max_series_growth is None
            else max_series_growth
        ),
        min_series_growth=(
            _BASE_GROWTH_GUARDRAIL.min_series_growth
            if min_series_growth is None
            else min_series_growth
        ),
        min_terminal_growth=(
            _BASE_GROWTH_GUARDRAIL.min_terminal_growth
            if min_terminal_growth is None
            else min_terminal_growth
        ),
        max_terminal_growth=(
            _BASE_GROWTH_GUARDRAIL.max_terminal_growth
            if max_terminal_growth is None
            else max_terminal_growth
        ),
        final_fade_years=(
            _BASE_GROWTH_GUARDRAIL.final_fade_years
            if final_fade_years is None
            else final_fade_years
        ),
        enforce_nonincreasing_trend=(
            _BASE_GROWTH_GUARDRAIL.enforce_nonincreasing_trend
            if enforce_nonincreasing_trend is None
            else enforce_nonincreasing_trend
        ),
    )


def _margin_config_from_base(
    *,
    min_series_margin: float | None = None,
    max_series_margin: float | None = None,
    normalized_margin_lower: float | None = None,
    normalized_margin_upper: float | None = None,
    final_fade_years: int | None = None,
) -> MarginGuardrailConfig:
    return MarginGuardrailConfig(
        min_series_margin=(
            _BASE_MARGIN_GUARDRAIL.min_series_margin
            if min_series_margin is None
            else min_series_margin
        ),
        max_series_margin=(
            _BASE_MARGIN_GUARDRAIL.max_series_margin
            if max_series_margin is None
            else max_series_margin
        ),
        normalized_margin_lower=(
            _BASE_MARGIN_GUARDRAIL.normalized_margin_lower
            if normalized_margin_lower is None
            else normalized_margin_lower
        ),
        normalized_margin_upper=(
            _BASE_MARGIN_GUARDRAIL.normalized_margin_upper
            if normalized_margin_upper is None
            else normalized_margin_upper
        ),
        final_fade_years=(
            _BASE_MARGIN_GUARDRAIL.final_fade_years
            if final_fade_years is None
            else final_fade_years
        ),
    )


def _reinvestment_config_from_base(
    *,
    base: ReinvestmentGuardrailConfig,
    min_series_rate: float | None = None,
    max_series_rate: float | None = None,
    terminal_lower: float | None = None,
    terminal_upper: float | None = None,
    final_fade_years: int | None = None,
) -> ReinvestmentGuardrailConfig:
    return ReinvestmentGuardrailConfig(
        min_series_rate=(
            base.min_series_rate if min_series_rate is None else min_series_rate
        ),
        max_series_rate=(
            base.max_series_rate if max_series_rate is None else max_series_rate
        ),
        terminal_lower=(
            base.terminal_lower if terminal_lower is None else terminal_lower
        ),
        terminal_upper=(
            base.terminal_upper if terminal_upper is None else terminal_upper
        ),
        final_fade_years=(
            base.final_fade_years if final_fade_years is None else final_fade_years
        ),
    )


_DCF_VARIANT_GUARDRAIL_PROFILES: dict[str, _VariantGuardrailProfile] = {
    "dcf_growth": _VariantGuardrailProfile(
        profile_name="dcf_growth",
        growth_config=_growth_config_from_base(
            max_year1_growth=0.50,
            max_series_growth=0.80,
            min_series_growth=-0.45,
            min_terminal_growth=-0.005,
            max_terminal_growth=0.035,
            final_fade_years=5,
            enforce_nonincreasing_trend=True,
        ),
        margin_config=_margin_config_from_base(
            min_series_margin=-0.25,
            max_series_margin=0.60,
            normalized_margin_lower=0.18,
            normalized_margin_upper=0.39,
            final_fade_years=5,
        ),
        capex_config=_reinvestment_config_from_base(
            base=_BASE_CAPEX_GUARDRAIL,
            min_series_rate=0.00,
            max_series_rate=0.30,
            terminal_lower=0.04,
            terminal_upper=0.11,
            final_fade_years=6,
        ),
        wc_config=_reinvestment_config_from_base(
            base=_BASE_WC_GUARDRAIL,
            min_series_rate=-0.08,
            max_series_rate=0.13,
            terminal_lower=-0.01,
            terminal_upper=0.045,
            final_fade_years=6,
        ),
        terminal_growth_floor=None,
    ),
    "dcf_standard": _VariantGuardrailProfile(
        profile_name="dcf_standard",
        growth_config=_growth_config_from_base(
            max_year1_growth=0.48,
            max_series_growth=0.70,
            min_series_growth=-0.35,
            min_terminal_growth=0.022,
            max_terminal_growth=0.048,
            final_fade_years=4,
            enforce_nonincreasing_trend=True,
        ),
        margin_config=_margin_config_from_base(
            min_series_margin=-0.20,
            max_series_margin=0.58,
            normalized_margin_lower=0.12,
            normalized_margin_upper=0.38,
            final_fade_years=3,
        ),
        capex_config=_reinvestment_config_from_base(
            base=_BASE_CAPEX_GUARDRAIL,
            min_series_rate=0.00,
            max_series_rate=0.24,
            terminal_lower=0.015,
            terminal_upper=0.075,
            final_fade_years=4,
        ),
        wc_config=_reinvestment_config_from_base(
            base=_BASE_WC_GUARDRAIL,
            min_series_rate=-0.06,
            max_series_rate=0.10,
            terminal_lower=-0.035,
            terminal_upper=0.04,
            final_fade_years=4,
        ),
        terminal_growth_floor=0.035,
    ),
}

DCF_SHARES_SCOPE_POLICY_ENV = "FUNDAMENTAL_DCF_SHARES_SCOPE_POLICY"
DCF_SHARES_SCOPE_POLICY_HARMONIZE = "harmonize_when_mismatch"
DCF_SHARES_SCOPE_POLICY_CONSERVATIVE_ONLY = "conservative_only"
DCF_STANDARD_CONSENSUS_TERMINAL_NUDGE_ENABLED_ENV = (
    "FUNDAMENTAL_DCF_STANDARD_CONSENSUS_TERMINAL_NUDGE_ENABLED"
)
DCF_STANDARD_CONSENSUS_PREMIUM_TRIGGER = 0.05
DCF_STANDARD_CONSENSUS_PREMIUM_CAP = 0.25
DCF_STANDARD_CONSENSUS_TERMINAL_NUDGE_SLOPE = 0.10
DCF_STANDARD_CONSENSUS_TERMINAL_NUDGE_MAX = 0.01
DCF_STANDARD_CONSENSUS_CONFIDENCE_FULL = 1.00
DCF_STANDARD_CONSENSUS_CONFIDENCE_MULTI_SOURCE = 0.75
DCF_STANDARD_CONSENSUS_CONFIDENCE_FALLBACK = 0.30
DCF_STANDARD_CONSENSUS_CONFIDENCE_SINGLE_SOURCE = 0.45
DCF_STANDARD_GROWTH_RELAX_PREMIUM_TRIGGER = 0.10
DCF_STANDARD_GROWTH_RELAX_PREMIUM_CAP = 0.20
DCF_STANDARD_GROWTH_RELAX_SLOPE = 0.50
DCF_STANDARD_GROWTH_RELAX_MAX = 0.05
DCF_STANDARD_GROWTH_RELAX_MAX_SERIES_CAP = 0.80
DCF_STANDARD_MARGIN_RELAX_PREMIUM_TRIGGER = 0.10
DCF_STANDARD_MARGIN_RELAX_PREMIUM_CAP = 0.20
DCF_STANDARD_MARGIN_RELAX_SLOPE = 0.35
DCF_STANDARD_MARGIN_RELAX_MAX = 0.025
DCF_STANDARD_MARGIN_RELAX_MAX_YEAR1_GROWTH = 0.22
DCF_STANDARD_CAPEX_RELAX_PREMIUM_TRIGGER = 0.10
DCF_STANDARD_CAPEX_RELAX_PREMIUM_CAP = 0.20
DCF_STANDARD_CAPEX_RELAX_SLOPE = 0.25
DCF_STANDARD_CAPEX_RELAX_MAX = 0.015
DCF_STANDARD_WC_RELAX_PREMIUM_TRIGGER = 0.10
DCF_STANDARD_WC_RELAX_PREMIUM_CAP = 0.20
DCF_STANDARD_WC_RELAX_SLOPE = 0.10
DCF_STANDARD_WC_RELAX_MAX = 0.008
DCF_STANDARD_RELAX_MIN_CONFIDENCE = 0.45
DCF_GROWTH_CAPEX_RELAX_PREMIUM_TRIGGER = 0.35
DCF_GROWTH_CAPEX_RELAX_PREMIUM_CAP = 0.25
DCF_GROWTH_CAPEX_RELAX_SLOPE = 0.50
DCF_GROWTH_CAPEX_RELAX_MAX = 0.04
DCF_GROWTH_DEGRADED_HIGH_PREMIUM_TRIGGER = 0.40
DCF_GROWTH_DEGRADED_HIGH_PREMIUM_CAPEX_TERMINAL_UPPER = 0.09
DCF_GROWTH_WC_RELAX_PREMIUM_TRIGGER = 0.30
DCF_GROWTH_WC_RELAX_PREMIUM_CAP = 0.25
DCF_GROWTH_WC_RELAX_SLOPE = 0.20
DCF_GROWTH_WC_RELAX_MAX = 0.02
DCF_GROWTH_MARGIN_RELAX_PREMIUM_TRIGGER = 0.35
DCF_GROWTH_MARGIN_RELAX_PREMIUM_CAP = 0.25
DCF_GROWTH_MARGIN_RELAX_SLOPE = 0.80
DCF_GROWTH_MARGIN_RELAX_MAX = 0.06
DCF_GROWTH_DEGRADED_HIGH_PREMIUM_MARGIN_UPPER_FLOOR = 0.44
DCF_GROWTH_TERMINAL_NUDGE_ENABLED_ENV = (
    "FUNDAMENTAL_DCF_GROWTH_CONSENSUS_TERMINAL_NUDGE_ENABLED"
)
DCF_GROWTH_TERMINAL_NUDGE_PREMIUM_TRIGGER = 0.30
DCF_GROWTH_TERMINAL_NUDGE_PREMIUM_CAP = 0.25
DCF_GROWTH_TERMINAL_NUDGE_SLOPE = 0.08
DCF_GROWTH_TERMINAL_NUDGE_MAX = 0.012
DCF_GROWTH_TERMINAL_NUDGE_MAX_TERMINAL = 0.035
DCF_GROWTH_DEGRADED_HIGH_PREMIUM_TERMINAL_NUDGE_MAX_TERMINAL = 0.040
DCF_GROWTH_TERMINAL_NUDGE_MAX_YEAR1_GROWTH = 0.25
DCF_GROWTH_DEGRADED_LOW_PREMIUM_TERMINAL_CAP = 0.020
DCF_GROWTH_DEGRADED_LOW_PREMIUM_PREMIUM_THRESHOLD = 0.30
DCF_GROWTH_MARGIN_RELAX_MAX_YEAR1_GROWTH = 0.25
DCF_GROWTH_LOW_PREMIUM_REINVESTMENT_PREMIUM_THRESHOLD = 0.30
DCF_GROWTH_LOW_PREMIUM_CAPEX_TERMINAL_LOWER_FLOOR = 0.08
DCF_GROWTH_LOW_PREMIUM_WC_TERMINAL_LOWER_FLOOR = 0.00
DCF_GROWTH_MISMATCH_LOW_PREMIUM_CAPEX_TERMINAL_LOWER_FLOOR = 0.12
DCF_GROWTH_MISMATCH_LOW_PREMIUM_CAPEX_TERMINAL_UPPER_FLOOR = 0.16
DCF_GROWTH_MISMATCH_LOW_PREMIUM_WC_TERMINAL_LOWER_FLOOR = 0.02
DCF_GROWTH_MISMATCH_LOW_PREMIUM_WC_TERMINAL_UPPER_FLOOR = 0.07


@dataclass(frozen=True)
class _VariantReinvestmentAnchors:
    capex_anchor: float | None
    wc_anchor: float | None
    capex_samples: int
    wc_samples: int


def build_dcf_variant_payload(
    *,
    payload: SaasBuildPayload,
    model_variant: str,
    reinvestment_anchors: _VariantReinvestmentAnchors | None = None,
    market_snapshot: Mapping[str, object] | None = None,
) -> SaasBuildPayload:
    params = dict(payload.params)
    params["model_variant"] = model_variant

    assumptions = list(payload.assumptions)
    assumptions.append(
        f"model_variant={model_variant} routed via dedicated param builder"
    )
    assumptions.append(
        f"guardrail_profile_version={_GUARDRAIL_PROFILE_VERSION};variant={model_variant}"
    )
    trace_inputs = dict(payload.trace_inputs)
    shares_source = payload.shares_source
    shares_path = (
        dict(payload.shares_path) if isinstance(payload.shares_path, Mapping) else None
    )

    shares_source, shares_path = _apply_variant_shares_scope_policy(
        params=params,
        assumptions=assumptions,
        trace_inputs=trace_inputs,
        shares_source=shares_source,
        shares_path=shares_path,
    )

    reinvestment_clamp_profile = load_reinvestment_clamp_profile()
    if reinvestment_clamp_profile.degraded_reason is None:
        assumptions.append(
            "reinvestment_clamp_profile loaded "
            f"(source={reinvestment_clamp_profile.profile_source}, "
            f"version={reinvestment_clamp_profile.profile.profile_version})"
        )
    else:
        assumptions.append(
            "reinvestment_clamp_profile fallback "
            f"(source={reinvestment_clamp_profile.profile_source}, "
            f"version={reinvestment_clamp_profile.profile.profile_version}, "
            f"reason={reinvestment_clamp_profile.degraded_reason})"
        )

    guardrail_profile = _DCF_VARIANT_GUARDRAIL_PROFILES.get(model_variant)
    if guardrail_profile is not None:
        if model_variant == "dcf_growth":
            _apply_dcf_growth_terminal_consensus_nudge(
                params=params,
                assumptions=assumptions,
                trace_inputs=trace_inputs,
                market_snapshot=market_snapshot,
                shares_path=shares_path,
            )
            _apply_dcf_growth_degraded_low_premium_terminal_cap(
                params=params,
                assumptions=assumptions,
                trace_inputs=trace_inputs,
                market_snapshot=market_snapshot,
            )
        growth_guardrail_config = guardrail_profile.growth_config
        margin_guardrail_config = guardrail_profile.margin_config
        capex_guardrail_config = guardrail_profile.capex_config
        if model_variant == "dcf_growth":
            margin_guardrail_config, margin_relax_assumption = (
                _resolve_dcf_growth_margin_guardrail_config(
                    config=guardrail_profile.margin_config,
                    params=params,
                    market_snapshot=market_snapshot,
                    shares_path=shares_path,
                )
            )
            if margin_relax_assumption is not None:
                assumptions.append(margin_relax_assumption)
            capex_guardrail_config, capex_relax_assumption = (
                _resolve_dcf_growth_capex_guardrail_config(
                    config=guardrail_profile.capex_config,
                    params=params,
                    market_snapshot=market_snapshot,
                    shares_path=shares_path,
                    reinvestment_clamp_profile=reinvestment_clamp_profile,
                )
            )
            if capex_relax_assumption is not None:
                assumptions.append(capex_relax_assumption)
            wc_guardrail_config, wc_relax_assumption = (
                _resolve_dcf_growth_wc_guardrail_config(
                    config=guardrail_profile.wc_config,
                    params=params,
                    market_snapshot=market_snapshot,
                    shares_path=shares_path,
                    reinvestment_clamp_profile=reinvestment_clamp_profile,
                )
            )
            if wc_relax_assumption is not None:
                assumptions.append(wc_relax_assumption)
        elif model_variant == "dcf_standard":
            growth_guardrail_config, growth_relax_assumption = (
                _resolve_dcf_standard_growth_guardrail_config(
                    config=guardrail_profile.growth_config,
                    market_snapshot=market_snapshot,
                )
            )
            if growth_relax_assumption is not None:
                assumptions.append(growth_relax_assumption)
            margin_guardrail_config, margin_relax_assumption = (
                _resolve_dcf_standard_margin_guardrail_config(
                    config=guardrail_profile.margin_config,
                    params=params,
                    market_snapshot=market_snapshot,
                )
            )
            if margin_relax_assumption is not None:
                assumptions.append(margin_relax_assumption)
            capex_guardrail_config, capex_relax_assumption = (
                _resolve_dcf_standard_capex_guardrail_config(
                    config=guardrail_profile.capex_config,
                    market_snapshot=market_snapshot,
                )
            )
            if capex_relax_assumption is not None:
                assumptions.append(capex_relax_assumption)
            wc_guardrail_config, wc_relax_assumption = (
                _resolve_dcf_standard_wc_guardrail_config(
                    config=guardrail_profile.wc_config,
                    market_snapshot=market_snapshot,
                )
            )
            if wc_relax_assumption is not None:
                assumptions.append(wc_relax_assumption)
        else:
            wc_guardrail_config = guardrail_profile.wc_config
        _apply_variant_terminal_growth_floor(
            params=params,
            assumptions=assumptions,
            trace_inputs=trace_inputs,
            profile=guardrail_profile,
            market_snapshot=market_snapshot,
        )
        guarded_growth_rates = _apply_variant_base_growth_guardrail(
            params=params,
            assumptions=assumptions,
            trace_inputs=trace_inputs,
            profile=guardrail_profile,
            config=growth_guardrail_config,
        )
        if guarded_growth_rates is not None:
            params["growth_rates"] = guarded_growth_rates
        guarded_margins = _apply_variant_base_margin_guardrail(
            params=params,
            assumptions=assumptions,
            trace_inputs=trace_inputs,
            profile=guardrail_profile,
            config=margin_guardrail_config,
        )
        if guarded_margins is not None:
            params["operating_margins"] = guarded_margins
        guarded_capex_rates = _apply_variant_reinvestment_guardrail(
            params=params,
            assumptions=assumptions,
            trace_inputs=trace_inputs,
            profile=guardrail_profile,
            metric_field="capex_rates",
            metric_prefix="capex",
            config=capex_guardrail_config,
            historical_anchor=(
                reinvestment_anchors.capex_anchor
                if isinstance(reinvestment_anchors, _VariantReinvestmentAnchors)
                else None
            ),
            anchor_samples=(
                reinvestment_anchors.capex_samples
                if isinstance(reinvestment_anchors, _VariantReinvestmentAnchors)
                else 0
            ),
        )
        if guarded_capex_rates is not None:
            params["capex_rates"] = guarded_capex_rates
        guarded_wc_rates = _apply_variant_reinvestment_guardrail(
            params=params,
            assumptions=assumptions,
            trace_inputs=trace_inputs,
            profile=guardrail_profile,
            metric_field="wc_rates",
            metric_prefix="wc",
            config=wc_guardrail_config,
            historical_anchor=(
                reinvestment_anchors.wc_anchor
                if isinstance(reinvestment_anchors, _VariantReinvestmentAnchors)
                else None
            ),
            anchor_samples=(
                reinvestment_anchors.wc_samples
                if isinstance(reinvestment_anchors, _VariantReinvestmentAnchors)
                else 0
            ),
        )
        if guarded_wc_rates is not None:
            params["wc_rates"] = guarded_wc_rates

    return SaasBuildPayload(
        params=params,
        trace_inputs=trace_inputs,
        missing=payload.missing,
        assumptions=assumptions,
        shares_source=shares_source,
        terminal_growth_path=payload.terminal_growth_path,
        shares_path=shares_path,
    )


def build_dcf_variant_model_payload(
    *,
    ticker: str | None,
    latest: FinancialReport,
    reports: list[FinancialReport],
    market_snapshot: Mapping[str, object] | None,
    saas_deps: SaasBuilderDeps,
    model_variant: str,
) -> SaasBuildPayload:
    reinvestment_anchors = _derive_variant_reinvestment_anchors(reports=reports)
    payload = build_saas_payload(
        ticker=ticker,
        latest=latest,
        reports=reports,
        market_snapshot=market_snapshot,
        deps=saas_deps,
    )
    return build_dcf_variant_payload(
        payload=payload,
        model_variant=model_variant,
        reinvestment_anchors=reinvestment_anchors,
        market_snapshot=market_snapshot,
    )


def _apply_variant_base_growth_guardrail(
    *,
    params: dict[str, object],
    assumptions: list[str],
    trace_inputs: dict[str, object],
    profile: _VariantGuardrailProfile,
    config: GrowthGuardrailConfig,
) -> list[float] | None:
    raw_growth = _coerce_numeric_series(params.get("growth_rates"))
    terminal_growth = _coerce_float(params.get("terminal_growth"))
    if not raw_growth or terminal_growth is None:
        return None

    result = apply_growth_guardrail(
        growth_rates=raw_growth,
        long_run_growth_target=terminal_growth,
        config=config,
    )
    if not result.hit:
        return None

    reasons = "|".join(result.reasons) if result.reasons else "none"
    assumptions.append(
        "base_growth_guardrail applied "
        f"(version={DEFAULT_BASE_ASSUMPTION_GUARDRAIL_VERSION}, "
        f"profile={profile.profile_name}, "
        f"raw_year1={result.raw_series[0]:.6f}, raw_yearN={result.raw_series[-1]:.6f}, "
        f"guarded_year1={result.guarded_series[0]:.6f}, guarded_yearN={result.guarded_series[-1]:.6f}, "
        f"reasons={reasons})"
    )

    trace_raw = trace_inputs.get("growth_rates")
    if isinstance(trace_raw, TraceableField):
        trace_inputs["growth_rates"] = trace_raw.model_copy(
            update={"value": list(result.guarded_series)}
        )
    return list(result.guarded_series)


def _apply_variant_terminal_growth_floor(
    *,
    params: dict[str, object],
    assumptions: list[str],
    trace_inputs: dict[str, object],
    profile: _VariantGuardrailProfile,
    market_snapshot: Mapping[str, object] | None,
) -> None:
    terminal_floor = profile.terminal_growth_floor
    if terminal_floor is None:
        return

    consensus_nudge = _resolve_consensus_terminal_nudge(
        profile=profile,
        market_snapshot=market_snapshot,
    )
    effective_terminal_floor = terminal_floor + consensus_nudge.nudge
    if consensus_nudge.nudge > 0:
        assumptions.append(
            "terminal_growth_consensus_nudge applied "
            f"(profile={profile.profile_name}, "
            f"premium={consensus_nudge.target_premium:.2%}, "
            f"confidence={consensus_nudge.confidence:.2f}, "
            f"nudge={consensus_nudge.nudge:.4f}, "
            f"base_floor={terminal_floor:.2%}, "
            f"effective_floor={effective_terminal_floor:.2%}, "
            f"target_consensus_applied={consensus_nudge.target_consensus_applied}, "
            f"source_count={consensus_nudge.source_count}, "
            f"fallback_reason={consensus_nudge.fallback_reason or 'none'}, "
            f"quality_bucket={consensus_nudge.quality_bucket or 'unknown'})"
        )

    raw_terminal_growth = _coerce_float(params.get("terminal_growth"))
    if raw_terminal_growth is None:
        return
    if raw_terminal_growth >= effective_terminal_floor:
        return

    params["terminal_growth"] = effective_terminal_floor
    assumptions.append(
        "terminal_growth_floor applied "
        f"(profile={profile.profile_name}, "
        f"raw={raw_terminal_growth:.6f}, "
        f"guarded={effective_terminal_floor:.6f})"
    )

    trace_raw = trace_inputs.get("terminal_growth")
    if isinstance(trace_raw, TraceableField):
        trace_inputs["terminal_growth"] = trace_raw.model_copy(
            update={"value": effective_terminal_floor}
        )


def _apply_variant_base_margin_guardrail(
    *,
    params: dict[str, object],
    assumptions: list[str],
    trace_inputs: dict[str, object],
    profile: _VariantGuardrailProfile,
    config: MarginGuardrailConfig,
) -> list[float] | None:
    raw_margins = _coerce_numeric_series(params.get("operating_margins"))
    if not raw_margins:
        return None

    result = apply_margin_guardrail(
        operating_margins=raw_margins,
        config=config,
    )
    if not result.hit:
        return None

    reasons = "|".join(result.reasons) if result.reasons else "none"
    assumptions.append(
        "base_margin_guardrail applied "
        f"(version={DEFAULT_BASE_ASSUMPTION_GUARDRAIL_VERSION}, "
        f"profile={profile.profile_name}, "
        f"raw_year1={result.raw_series[0]:.6f}, raw_yearN={result.raw_series[-1]:.6f}, "
        f"guarded_year1={result.guarded_series[0]:.6f}, guarded_yearN={result.guarded_series[-1]:.6f}, "
        f"reasons={reasons})"
    )

    trace_raw = trace_inputs.get("operating_margins")
    if isinstance(trace_raw, TraceableField):
        trace_inputs["operating_margins"] = trace_raw.model_copy(
            update={"value": list(result.guarded_series)}
        )
    return list(result.guarded_series)


def _apply_variant_reinvestment_guardrail(
    *,
    params: dict[str, object],
    assumptions: list[str],
    trace_inputs: dict[str, object],
    profile: _VariantGuardrailProfile,
    metric_field: str,
    metric_prefix: str,
    config: ReinvestmentGuardrailConfig,
    historical_anchor: float | None,
    anchor_samples: int,
) -> list[float] | None:
    raw_rates = _coerce_numeric_series(params.get(metric_field))
    if not raw_rates:
        return None

    result = apply_reinvestment_guardrail(
        series_rates=raw_rates,
        config=config,
        metric_prefix=metric_prefix,
        historical_anchor=historical_anchor,
    )
    if not result.hit:
        return None

    reasons = "|".join(result.reasons) if result.reasons else "none"
    anchor_text = (
        f"{historical_anchor:.6f}" if isinstance(historical_anchor, float) else "none"
    )
    assumptions.append(
        "base_reinvestment_guardrail applied "
        f"(version={DEFAULT_BASE_ASSUMPTION_GUARDRAIL_VERSION}, "
        f"profile={profile.profile_name}, metric={metric_field}, "
        f"raw_year1={result.raw_series[0]:.6f}, raw_yearN={result.raw_series[-1]:.6f}, "
        f"guarded_year1={result.guarded_series[0]:.6f}, "
        f"guarded_yearN={result.guarded_series[-1]:.6f}, "
        f"anchor={anchor_text}, anchor_samples={anchor_samples}, reasons={reasons})"
    )

    trace_raw = trace_inputs.get(metric_field)
    if isinstance(trace_raw, TraceableField):
        trace_inputs[metric_field] = trace_raw.model_copy(
            update={"value": list(result.guarded_series)}
        )
    return list(result.guarded_series)


def _derive_variant_reinvestment_anchors(
    *,
    reports: list[FinancialReport],
) -> _VariantReinvestmentAnchors:
    capex_rates: list[float] = []
    wc_rates: list[float] = []

    for report in reports:
        revenue = _coerce_float(report.base.total_revenue.value)
        if revenue is None or revenue <= 0:
            continue
        extension = report.extension
        if not isinstance(extension, IndustrialExtension):
            continue
        capex_value = _coerce_float(extension.capex.value)
        if capex_value is None:
            continue
        capex_rates.append(abs(capex_value) / revenue)

    for idx in range(0, len(reports) - 1):
        current = reports[idx]
        previous = reports[idx + 1]
        revenue = _coerce_float(current.base.total_revenue.value)
        if revenue is None or revenue <= 0:
            continue
        current_wc = _extract_working_capital(current)
        previous_wc = _extract_working_capital(previous)
        if current_wc is None or previous_wc is None:
            continue
        wc_rates.append((current_wc - previous_wc) / revenue)

    capex_anchor = median(capex_rates) if capex_rates else None
    wc_anchor = median(wc_rates) if wc_rates else None

    return _VariantReinvestmentAnchors(
        capex_anchor=capex_anchor,
        wc_anchor=wc_anchor,
        capex_samples=len(capex_rates),
        wc_samples=len(wc_rates),
    )


def _extract_working_capital(report: FinancialReport) -> float | None:
    current_assets = _coerce_float(report.base.current_assets.value)
    current_liabilities = _coerce_float(report.base.current_liabilities.value)
    if current_assets is None or current_liabilities is None:
        return None
    return current_assets - current_liabilities


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


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


def _coerce_numeric_series(value: object) -> list[float] | None:
    if not isinstance(value, list | tuple):
        return None
    output: list[float] = []
    for item in value:
        number = _coerce_float(item)
        if number is None:
            return None
        output.append(number)
    return output or None


@dataclass(frozen=True)
class _ConsensusTerminalNudge:
    nudge: float
    target_premium: float
    confidence: float
    target_consensus_applied: bool
    source_count: int
    fallback_reason: str | None
    quality_bucket: str | None


@dataclass(frozen=True)
class _ConsensusAnchorSignal:
    target_premium: float
    confidence: float
    target_consensus_applied: bool
    source_count: int
    fallback_reason: str | None
    quality_bucket: str | None


def _resolve_consensus_terminal_nudge_enabled() -> bool:
    raw = os.getenv(DCF_STANDARD_CONSENSUS_TERMINAL_NUDGE_ENABLED_ENV)
    if raw is None:
        return True
    parsed = _coerce_bool(raw)
    return True if parsed is None else parsed


def _resolve_dcf_growth_terminal_nudge_enabled() -> bool:
    raw = os.getenv(DCF_GROWTH_TERMINAL_NUDGE_ENABLED_ENV)
    if raw is None:
        return True
    parsed = _coerce_bool(raw)
    return True if parsed is None else parsed


def _resolve_consensus_anchor_signal(
    *,
    market_snapshot: Mapping[str, object] | None,
) -> _ConsensusAnchorSignal | None:
    if not isinstance(market_snapshot, Mapping):
        return None
    current_price = _coerce_float(market_snapshot.get("current_price"))
    target_mean_price = _coerce_float(market_snapshot.get("target_mean_price"))
    if (
        current_price is None
        or current_price <= 0
        or target_mean_price is None
        or target_mean_price <= 0
    ):
        return None

    premium = (target_mean_price / current_price) - 1.0
    applied_raw = _coerce_bool(market_snapshot.get("target_consensus_applied"))
    target_consensus_applied = bool(applied_raw) if applied_raw is not None else False
    source_count_raw = _coerce_int(market_snapshot.get("target_consensus_source_count"))
    source_count = (
        source_count_raw
        if isinstance(source_count_raw, int) and source_count_raw > 0
        else 1
    )
    fallback_reason_raw = market_snapshot.get("target_consensus_fallback_reason")
    fallback_reason = (
        fallback_reason_raw
        if isinstance(fallback_reason_raw, str) and fallback_reason_raw
        else None
    )
    quality_bucket_raw = market_snapshot.get("target_consensus_quality_bucket")
    quality_bucket = (
        quality_bucket_raw
        if isinstance(quality_bucket_raw, str) and quality_bucket_raw
        else None
    )
    confidence_weight_raw = market_snapshot.get("target_consensus_confidence_weight")
    confidence_weight = (
        float(confidence_weight_raw)
        if isinstance(confidence_weight_raw, int | float)
        else None
    )
    if confidence_weight is not None:
        confidence = _clamp(confidence_weight, 0.0, 1.0)
    elif quality_bucket == "high":
        confidence = DCF_STANDARD_CONSENSUS_CONFIDENCE_FULL
    elif quality_bucket == "medium":
        confidence = DCF_STANDARD_CONSENSUS_CONFIDENCE_MULTI_SOURCE
    elif quality_bucket == "low":
        confidence = DCF_STANDARD_CONSENSUS_CONFIDENCE_SINGLE_SOURCE
    elif quality_bucket == "degraded":
        confidence = DCF_STANDARD_CONSENSUS_CONFIDENCE_FALLBACK
    elif target_consensus_applied and source_count >= 2:
        confidence = DCF_STANDARD_CONSENSUS_CONFIDENCE_FULL
    elif source_count >= 2:
        confidence = DCF_STANDARD_CONSENSUS_CONFIDENCE_MULTI_SOURCE
    elif fallback_reason is not None:
        confidence = DCF_STANDARD_CONSENSUS_CONFIDENCE_FALLBACK
    else:
        confidence = DCF_STANDARD_CONSENSUS_CONFIDENCE_SINGLE_SOURCE

    if (
        source_count <= 1
        and confidence > DCF_STANDARD_CONSENSUS_CONFIDENCE_SINGLE_SOURCE
    ):
        confidence = DCF_STANDARD_CONSENSUS_CONFIDENCE_SINGLE_SOURCE

    return _ConsensusAnchorSignal(
        target_premium=premium,
        confidence=confidence,
        target_consensus_applied=target_consensus_applied,
        source_count=source_count,
        fallback_reason=fallback_reason,
        quality_bucket=quality_bucket,
    )


def _apply_dcf_growth_terminal_consensus_nudge(
    *,
    params: dict[str, object],
    assumptions: list[str],
    trace_inputs: dict[str, object],
    market_snapshot: Mapping[str, object] | None,
    shares_path: Mapping[str, object] | None,
) -> None:
    if not _resolve_dcf_growth_terminal_nudge_enabled():
        return

    mismatch_detected_raw = (
        shares_path.get("scope_mismatch_detected")
        if isinstance(shares_path, Mapping)
        else None
    )
    if isinstance(mismatch_detected_raw, bool) and mismatch_detected_raw:
        assumptions.append(
            "dcf_growth_terminal_consensus_nudge skipped "
            "(shares_scope_mismatch_detected=true)"
        )
        return

    growth_rates = _coerce_numeric_series(params.get("growth_rates"))
    year1_growth = growth_rates[0] if growth_rates else None
    if (
        isinstance(year1_growth, float)
        and year1_growth > DCF_GROWTH_TERMINAL_NUDGE_MAX_YEAR1_GROWTH
    ):
        assumptions.append(
            "dcf_growth_terminal_consensus_nudge skipped "
            f"(year1_growth={year1_growth:.4f} > "
            f"threshold={DCF_GROWTH_TERMINAL_NUDGE_MAX_YEAR1_GROWTH:.4f})"
        )
        return

    signal = _resolve_consensus_anchor_signal(market_snapshot=market_snapshot)
    if signal is None:
        return
    if signal.target_premium <= DCF_GROWTH_TERMINAL_NUDGE_PREMIUM_TRIGGER:
        return

    raw_terminal = _coerce_float(params.get("terminal_growth"))
    if raw_terminal is None:
        return

    premium_signal = _clamp(
        signal.target_premium - DCF_GROWTH_TERMINAL_NUDGE_PREMIUM_TRIGGER,
        0.0,
        DCF_GROWTH_TERMINAL_NUDGE_PREMIUM_CAP,
    )
    nudge = min(
        DCF_GROWTH_TERMINAL_NUDGE_MAX,
        premium_signal * DCF_GROWTH_TERMINAL_NUDGE_SLOPE * signal.confidence,
    )
    if nudge <= 0:
        return

    degraded_high_premium = (
        signal.target_premium > DCF_GROWTH_DEGRADED_HIGH_PREMIUM_TRIGGER
        and (signal.fallback_reason is not None or signal.quality_bucket == "degraded")
    )
    max_terminal_cap = (
        DCF_GROWTH_DEGRADED_HIGH_PREMIUM_TERMINAL_NUDGE_MAX_TERMINAL
        if degraded_high_premium
        else DCF_GROWTH_TERMINAL_NUDGE_MAX_TERMINAL
    )
    adjusted_terminal = min(
        max_terminal_cap,
        raw_terminal + nudge,
    )
    if adjusted_terminal <= raw_terminal:
        return

    params["terminal_growth"] = adjusted_terminal
    assumptions.append(
        "dcf_growth_terminal_consensus_nudge applied "
        f"(premium={signal.target_premium:.2%}, confidence={signal.confidence:.2f}, "
        f"nudge={nudge:.4f}, raw_terminal={raw_terminal:.4f}, "
        f"adjusted_terminal={adjusted_terminal:.4f}, "
        f"max_terminal_cap={max_terminal_cap:.4f}, "
        f"target_consensus_applied={signal.target_consensus_applied}, "
        f"source_count={signal.source_count}, "
        f"fallback_reason={signal.fallback_reason or 'none'}, "
        f"quality_bucket={signal.quality_bucket or 'unknown'})"
    )

    trace_raw = trace_inputs.get("terminal_growth")
    if isinstance(trace_raw, TraceableField):
        trace_inputs["terminal_growth"] = trace_raw.model_copy(
            update={"value": adjusted_terminal}
        )


def _resolve_consensus_terminal_nudge(
    *,
    profile: _VariantGuardrailProfile,
    market_snapshot: Mapping[str, object] | None,
) -> _ConsensusTerminalNudge:
    if profile.profile_name != "dcf_standard":
        return _ConsensusTerminalNudge(
            nudge=0.0,
            target_premium=0.0,
            confidence=0.0,
            target_consensus_applied=False,
            source_count=0,
            fallback_reason=None,
            quality_bucket=None,
        )
    if not _resolve_consensus_terminal_nudge_enabled():
        return _ConsensusTerminalNudge(
            nudge=0.0,
            target_premium=0.0,
            confidence=0.0,
            target_consensus_applied=False,
            source_count=0,
            fallback_reason=None,
            quality_bucket=None,
        )
    signal = _resolve_consensus_anchor_signal(market_snapshot=market_snapshot)
    if signal is None:
        return _ConsensusTerminalNudge(
            nudge=0.0,
            target_premium=0.0,
            confidence=0.0,
            target_consensus_applied=False,
            source_count=0,
            fallback_reason=None,
            quality_bucket=None,
        )

    premium = signal.target_premium
    if premium <= DCF_STANDARD_CONSENSUS_PREMIUM_TRIGGER:
        return _ConsensusTerminalNudge(
            nudge=0.0,
            target_premium=premium,
            confidence=0.0,
            target_consensus_applied=False,
            source_count=0,
            fallback_reason=None,
            quality_bucket=None,
        )
    confidence = signal.confidence

    premium_signal = _clamp(
        premium - DCF_STANDARD_CONSENSUS_PREMIUM_TRIGGER,
        0.0,
        DCF_STANDARD_CONSENSUS_PREMIUM_CAP,
    )
    nudge = min(
        DCF_STANDARD_CONSENSUS_TERMINAL_NUDGE_MAX,
        premium_signal * DCF_STANDARD_CONSENSUS_TERMINAL_NUDGE_SLOPE * confidence,
    )
    return _ConsensusTerminalNudge(
        nudge=nudge,
        target_premium=premium,
        confidence=confidence,
        target_consensus_applied=signal.target_consensus_applied,
        source_count=signal.source_count,
        fallback_reason=signal.fallback_reason,
        quality_bucket=signal.quality_bucket,
    )


def _apply_dcf_growth_degraded_low_premium_terminal_cap(
    *,
    params: dict[str, object],
    assumptions: list[str],
    trace_inputs: dict[str, object],
    market_snapshot: Mapping[str, object] | None,
) -> None:
    signal = _resolve_consensus_anchor_signal(market_snapshot=market_snapshot)
    if signal is None:
        return
    if signal.target_premium > DCF_GROWTH_DEGRADED_LOW_PREMIUM_PREMIUM_THRESHOLD:
        return
    is_degraded = (
        signal.fallback_reason is not None
        or signal.quality_bucket == "degraded"
        or (not signal.target_consensus_applied and signal.source_count <= 1)
    )
    if not is_degraded:
        return
    raw_terminal = _coerce_float(params.get("terminal_growth"))
    if raw_terminal is None:
        return
    capped_terminal = min(raw_terminal, DCF_GROWTH_DEGRADED_LOW_PREMIUM_TERMINAL_CAP)
    if capped_terminal >= raw_terminal:
        return

    params["terminal_growth"] = capped_terminal
    assumptions.append(
        "dcf_growth_degraded_low_premium_terminal_cap applied "
        f"(target_premium={signal.target_premium:.2%}, "
        f"raw_terminal={raw_terminal:.4f}, capped_terminal={capped_terminal:.4f}, "
        f"fallback_reason={signal.fallback_reason or 'none'}, "
        f"quality_bucket={signal.quality_bucket or 'unknown'}, "
        f"source_count={signal.source_count})"
    )

    trace_raw = trace_inputs.get("terminal_growth")
    if isinstance(trace_raw, TraceableField):
        trace_inputs["terminal_growth"] = trace_raw.model_copy(
            update={"value": capped_terminal}
        )


def _resolve_dcf_growth_capex_guardrail_config(
    *,
    config: ReinvestmentGuardrailConfig,
    params: Mapping[str, object],
    market_snapshot: Mapping[str, object] | None,
    shares_path: Mapping[str, object] | None,
    reinvestment_clamp_profile: ReinvestmentClampProfileLoadResult,
) -> tuple[ReinvestmentGuardrailConfig, str | None]:
    signal = _resolve_consensus_anchor_signal(market_snapshot=market_snapshot)
    if signal is None:
        return config, None
    scope_mismatch_detected = _is_shares_scope_mismatch_detected(shares_path)
    if signal.target_premium <= DCF_GROWTH_LOW_PREMIUM_REINVESTMENT_PREMIUM_THRESHOLD:
        adjusted_lower = max(
            config.terminal_lower, DCF_GROWTH_LOW_PREMIUM_CAPEX_TERMINAL_LOWER_FLOOR
        )
        base_adjusted_lower = adjusted_lower
        adjusted_upper = config.terminal_upper
        if scope_mismatch_detected:
            adjusted_lower = max(
                adjusted_lower,
                DCF_GROWTH_MISMATCH_LOW_PREMIUM_CAPEX_TERMINAL_LOWER_FLOOR,
            )
            adjusted_upper = max(
                adjusted_upper,
                DCF_GROWTH_MISMATCH_LOW_PREMIUM_CAPEX_TERMINAL_UPPER_FLOOR,
            )
        severe_floor_applied = False
        severe_floor_target: float | None = None
        if _should_apply_severe_harmonized_mismatch_reinvestment_floor(
            signal=signal,
            shares_path=shares_path,
            reinvestment_clamp_profile=reinvestment_clamp_profile,
        ):
            capex_year1 = _resolve_series_year1(params=params, field="capex_rates")
            if capex_year1 is not None:
                profile = reinvestment_clamp_profile.profile.dcf_growth
                severe_floor_target = max(
                    profile.severe_mismatch_capex_terminal_lower_min,
                    capex_year1
                    * profile.severe_mismatch_capex_terminal_lower_year1_ratio,
                )
                if severe_floor_target > adjusted_lower:
                    severe_floor_applied = True
                    adjusted_lower = severe_floor_target
                    adjusted_upper = max(adjusted_upper, adjusted_lower + 0.005)
        if (
            adjusted_lower > config.terminal_lower
            or adjusted_upper > config.terminal_upper
        ):
            adjusted_config = ReinvestmentGuardrailConfig(
                min_series_rate=config.min_series_rate,
                max_series_rate=config.max_series_rate,
                terminal_lower=adjusted_lower,
                terminal_upper=adjusted_upper,
                final_fade_years=config.final_fade_years,
            )
            assumption_parts = [
                "dcf_growth_capex_low_premium_conservative_floor applied "
                f"(premium={signal.target_premium:.2%}, "
                f"terminal_lower_raw={config.terminal_lower:.4f}, "
                f"terminal_lower_adjusted={adjusted_lower:.4f}, "
                f"target_consensus_applied={signal.target_consensus_applied}, "
                f"source_count={signal.source_count}, "
                f"fallback_reason={signal.fallback_reason or 'none'}, "
                f"quality_bucket={signal.quality_bucket or 'unknown'})"
            ]
            if adjusted_upper > config.terminal_upper:
                assumption_parts.append(
                    "dcf_growth_capex_shares_mismatch_conservative_upper applied "
                    f"(premium={signal.target_premium:.2%}, "
                    f"terminal_upper_raw={config.terminal_upper:.4f}, "
                    f"terminal_upper_adjusted={adjusted_upper:.4f})"
                )
            if adjusted_lower > base_adjusted_lower:
                assumption_parts.append(
                    "dcf_growth_capex_shares_mismatch_conservative_floor applied "
                    f"(premium={signal.target_premium:.2%}, "
                    f"terminal_lower_raw={base_adjusted_lower:.4f}, "
                    f"terminal_lower_adjusted={adjusted_lower:.4f})"
                )
            if severe_floor_applied and severe_floor_target is not None:
                assumption_parts.append(
                    "dcf_growth_capex_harmonized_mismatch_severe_floor applied "
                    f"(premium={signal.target_premium:.2%}, "
                    f"terminal_lower_adjusted={severe_floor_target:.4f}, "
                    f"profile_version={reinvestment_clamp_profile.profile.profile_version}, "
                    f"rule=max({reinvestment_clamp_profile.profile.dcf_growth.severe_mismatch_capex_terminal_lower_min:.4f}, "
                    f"year1*{reinvestment_clamp_profile.profile.dcf_growth.severe_mismatch_capex_terminal_lower_year1_ratio:.2f}))"
                )
            return adjusted_config, "; ".join(assumption_parts)
        return config, None
    if signal.target_premium <= DCF_GROWTH_CAPEX_RELAX_PREMIUM_TRIGGER:
        return config, None

    premium_signal = _clamp(
        signal.target_premium - DCF_GROWTH_CAPEX_RELAX_PREMIUM_TRIGGER,
        0.0,
        DCF_GROWTH_CAPEX_RELAX_PREMIUM_CAP,
    )
    relax_delta = min(
        DCF_GROWTH_CAPEX_RELAX_MAX,
        premium_signal * DCF_GROWTH_CAPEX_RELAX_SLOPE * signal.confidence,
    )
    if relax_delta <= 0:
        return config, None

    adjusted_upper = max(
        config.terminal_lower + 0.005, config.terminal_upper - relax_delta
    )
    capex_assumption = (
        "dcf_growth_capex_consensus_relaxation applied "
        f"(premium={signal.target_premium:.2%}, confidence={signal.confidence:.2f}, "
        f"terminal_upper_raw={config.terminal_upper:.4f}, "
        f"terminal_upper_adjusted={adjusted_upper:.4f}, "
        f"target_consensus_applied={signal.target_consensus_applied}, "
        f"source_count={signal.source_count}, "
        f"fallback_reason={signal.fallback_reason or 'none'}, "
        f"quality_bucket={signal.quality_bucket or 'unknown'})"
    )

    degraded_high_premium = (
        signal.target_premium > DCF_GROWTH_DEGRADED_HIGH_PREMIUM_TRIGGER
        and (signal.fallback_reason is not None or signal.quality_bucket == "degraded")
    )
    if (
        degraded_high_premium
        and adjusted_upper > DCF_GROWTH_DEGRADED_HIGH_PREMIUM_CAPEX_TERMINAL_UPPER
    ):
        adjusted_upper = DCF_GROWTH_DEGRADED_HIGH_PREMIUM_CAPEX_TERMINAL_UPPER
        capex_assumption = (
            f"{capex_assumption}; "
            "dcf_growth_capex_degraded_high_premium_cap applied "
            f"(premium={signal.target_premium:.2%}, "
            f"capped_terminal_upper={adjusted_upper:.4f})"
        )

    if adjusted_upper >= config.terminal_upper:
        return config, None
    adjusted_config = ReinvestmentGuardrailConfig(
        min_series_rate=config.min_series_rate,
        max_series_rate=config.max_series_rate,
        terminal_lower=config.terminal_lower,
        terminal_upper=adjusted_upper,
        final_fade_years=config.final_fade_years,
    )
    return adjusted_config, capex_assumption


def _resolve_dcf_growth_margin_guardrail_config(
    *,
    config: MarginGuardrailConfig,
    params: Mapping[str, object],
    market_snapshot: Mapping[str, object] | None,
    shares_path: Mapping[str, object] | None,
) -> tuple[MarginGuardrailConfig, str | None]:
    mismatch_detected_raw = (
        shares_path.get("scope_mismatch_detected")
        if isinstance(shares_path, Mapping)
        else None
    )
    if isinstance(mismatch_detected_raw, bool) and mismatch_detected_raw:
        return (
            config,
            "dcf_growth_margin_consensus_relaxation skipped "
            "(shares_scope_mismatch_detected=true)",
        )

    growth_rates = _coerce_numeric_series(params.get("growth_rates"))
    year1_growth = growth_rates[0] if growth_rates else None
    if (
        isinstance(year1_growth, float)
        and year1_growth > DCF_GROWTH_MARGIN_RELAX_MAX_YEAR1_GROWTH
    ):
        return (
            config,
            "dcf_growth_margin_consensus_relaxation skipped "
            f"(year1_growth={year1_growth:.4f} > "
            f"threshold={DCF_GROWTH_MARGIN_RELAX_MAX_YEAR1_GROWTH:.4f})",
        )

    signal = _resolve_consensus_anchor_signal(market_snapshot=market_snapshot)
    if signal is None:
        return config, None
    if signal.target_premium <= DCF_GROWTH_MARGIN_RELAX_PREMIUM_TRIGGER:
        return config, None

    premium_signal = _clamp(
        signal.target_premium - DCF_GROWTH_MARGIN_RELAX_PREMIUM_TRIGGER,
        0.0,
        DCF_GROWTH_MARGIN_RELAX_PREMIUM_CAP,
    )
    relax_delta = min(
        DCF_GROWTH_MARGIN_RELAX_MAX,
        premium_signal * DCF_GROWTH_MARGIN_RELAX_SLOPE * signal.confidence,
    )
    if relax_delta <= 0:
        return config, None

    adjusted_upper = min(
        config.max_series_margin,
        config.normalized_margin_upper + relax_delta,
    )
    if adjusted_upper <= config.normalized_margin_upper:
        return config, None
    if adjusted_upper <= config.normalized_margin_lower:
        return config, None

    degraded_high_premium = (
        signal.target_premium > DCF_GROWTH_DEGRADED_HIGH_PREMIUM_TRIGGER
        and (signal.fallback_reason is not None or signal.quality_bucket == "degraded")
    )
    margin_assumption = (
        "dcf_growth_margin_consensus_relaxation applied "
        f"(premium={signal.target_premium:.2%}, confidence={signal.confidence:.2f}, "
        f"normalized_upper_raw={config.normalized_margin_upper:.4f}, "
        f"normalized_upper_adjusted={adjusted_upper:.4f}, "
        f"target_consensus_applied={signal.target_consensus_applied}, "
        f"source_count={signal.source_count}, "
        f"fallback_reason={signal.fallback_reason or 'none'}, "
        f"quality_bucket={signal.quality_bucket or 'unknown'})"
    )
    if (
        degraded_high_premium
        and adjusted_upper < DCF_GROWTH_DEGRADED_HIGH_PREMIUM_MARGIN_UPPER_FLOOR
    ):
        adjusted_upper = min(
            config.max_series_margin,
            DCF_GROWTH_DEGRADED_HIGH_PREMIUM_MARGIN_UPPER_FLOOR,
        )
        margin_assumption = (
            f"{margin_assumption}; "
            "dcf_growth_margin_degraded_high_premium_floor applied "
            f"(premium={signal.target_premium:.2%}, "
            f"adjusted_upper={adjusted_upper:.4f})"
        )

    adjusted_config = MarginGuardrailConfig(
        min_series_margin=config.min_series_margin,
        max_series_margin=config.max_series_margin,
        normalized_margin_lower=config.normalized_margin_lower,
        normalized_margin_upper=adjusted_upper,
        final_fade_years=config.final_fade_years,
    )
    return adjusted_config, margin_assumption


def _resolve_dcf_growth_wc_guardrail_config(
    *,
    config: ReinvestmentGuardrailConfig,
    params: Mapping[str, object],
    market_snapshot: Mapping[str, object] | None,
    shares_path: Mapping[str, object] | None,
    reinvestment_clamp_profile: ReinvestmentClampProfileLoadResult,
) -> tuple[ReinvestmentGuardrailConfig, str | None]:
    signal = _resolve_consensus_anchor_signal(market_snapshot=market_snapshot)
    if signal is None:
        return config, None
    scope_mismatch_detected = _is_shares_scope_mismatch_detected(shares_path)
    if signal.target_premium <= DCF_GROWTH_LOW_PREMIUM_REINVESTMENT_PREMIUM_THRESHOLD:
        adjusted_lower = max(
            config.terminal_lower, DCF_GROWTH_LOW_PREMIUM_WC_TERMINAL_LOWER_FLOOR
        )
        base_adjusted_lower = adjusted_lower
        adjusted_upper = config.terminal_upper
        if scope_mismatch_detected:
            adjusted_lower = max(
                adjusted_lower,
                DCF_GROWTH_MISMATCH_LOW_PREMIUM_WC_TERMINAL_LOWER_FLOOR,
            )
            adjusted_upper = max(
                adjusted_upper,
                DCF_GROWTH_MISMATCH_LOW_PREMIUM_WC_TERMINAL_UPPER_FLOOR,
            )
        severe_floor_applied = False
        severe_floor_target: float | None = None
        if _should_apply_severe_harmonized_mismatch_reinvestment_floor(
            signal=signal,
            shares_path=shares_path,
            reinvestment_clamp_profile=reinvestment_clamp_profile,
        ):
            wc_year1 = _resolve_series_year1(params=params, field="wc_rates")
            if wc_year1 is not None:
                profile = reinvestment_clamp_profile.profile.dcf_growth
                severe_floor_target = max(
                    profile.severe_mismatch_wc_terminal_lower_min,
                    wc_year1 * profile.severe_mismatch_wc_terminal_lower_year1_ratio,
                )
                if severe_floor_target > adjusted_lower:
                    severe_floor_applied = True
                    adjusted_lower = severe_floor_target
                    adjusted_upper = max(adjusted_upper, adjusted_lower + 0.005)
        if (
            adjusted_lower > config.terminal_lower
            or adjusted_upper > config.terminal_upper
        ):
            adjusted_config = ReinvestmentGuardrailConfig(
                min_series_rate=config.min_series_rate,
                max_series_rate=config.max_series_rate,
                terminal_lower=adjusted_lower,
                terminal_upper=adjusted_upper,
                final_fade_years=config.final_fade_years,
            )
            assumption_parts = [
                "dcf_growth_wc_low_premium_conservative_floor applied "
                f"(premium={signal.target_premium:.2%}, "
                f"terminal_lower_raw={config.terminal_lower:.4f}, "
                f"terminal_lower_adjusted={adjusted_lower:.4f}, "
                f"target_consensus_applied={signal.target_consensus_applied}, "
                f"source_count={signal.source_count}, "
                f"fallback_reason={signal.fallback_reason or 'none'}, "
                f"quality_bucket={signal.quality_bucket or 'unknown'})"
            ]
            if adjusted_upper > config.terminal_upper:
                assumption_parts.append(
                    "dcf_growth_wc_shares_mismatch_conservative_upper applied "
                    f"(premium={signal.target_premium:.2%}, "
                    f"terminal_upper_raw={config.terminal_upper:.4f}, "
                    f"terminal_upper_adjusted={adjusted_upper:.4f})"
                )
            if adjusted_lower > base_adjusted_lower:
                assumption_parts.append(
                    "dcf_growth_wc_shares_mismatch_conservative_floor applied "
                    f"(premium={signal.target_premium:.2%}, "
                    f"terminal_lower_raw={base_adjusted_lower:.4f}, "
                    f"terminal_lower_adjusted={adjusted_lower:.4f})"
                )
            if severe_floor_applied and severe_floor_target is not None:
                assumption_parts.append(
                    "dcf_growth_wc_harmonized_mismatch_severe_floor applied "
                    f"(premium={signal.target_premium:.2%}, "
                    f"terminal_lower_adjusted={severe_floor_target:.4f}, "
                    f"profile_version={reinvestment_clamp_profile.profile.profile_version}, "
                    f"rule=max({reinvestment_clamp_profile.profile.dcf_growth.severe_mismatch_wc_terminal_lower_min:.4f}, "
                    f"year1*{reinvestment_clamp_profile.profile.dcf_growth.severe_mismatch_wc_terminal_lower_year1_ratio:.2f}))"
                )
            return adjusted_config, "; ".join(assumption_parts)
        return config, None
    if signal.target_premium <= DCF_GROWTH_WC_RELAX_PREMIUM_TRIGGER:
        return config, None

    premium_signal = _clamp(
        signal.target_premium - DCF_GROWTH_WC_RELAX_PREMIUM_TRIGGER,
        0.0,
        DCF_GROWTH_WC_RELAX_PREMIUM_CAP,
    )
    relax_delta = min(
        DCF_GROWTH_WC_RELAX_MAX,
        premium_signal * DCF_GROWTH_WC_RELAX_SLOPE * signal.confidence,
    )
    if relax_delta <= 0:
        return config, None

    adjusted_lower = min(
        config.terminal_upper - 0.005, config.terminal_lower - relax_delta
    )
    if adjusted_lower <= config.terminal_lower:
        adjusted_config = ReinvestmentGuardrailConfig(
            min_series_rate=config.min_series_rate,
            max_series_rate=config.max_series_rate,
            terminal_lower=adjusted_lower,
            terminal_upper=config.terminal_upper,
            final_fade_years=config.final_fade_years,
        )
        return (
            adjusted_config,
            "dcf_growth_wc_consensus_relaxation applied "
            f"(premium={signal.target_premium:.2%}, confidence={signal.confidence:.2f}, "
            f"terminal_lower_raw={config.terminal_lower:.4f}, "
            f"terminal_lower_adjusted={adjusted_lower:.4f}, "
            f"target_consensus_applied={signal.target_consensus_applied}, "
            f"source_count={signal.source_count}, "
            f"fallback_reason={signal.fallback_reason or 'none'}, "
            f"quality_bucket={signal.quality_bucket or 'unknown'})",
        )
    return config, None


def _is_shares_scope_mismatch_detected(
    shares_path: Mapping[str, object] | None,
) -> bool:
    if not isinstance(shares_path, Mapping):
        return False
    raw_value = shares_path.get("scope_mismatch_detected")
    return isinstance(raw_value, bool) and raw_value


def _resolve_series_year1(
    *,
    params: Mapping[str, object],
    field: str,
) -> float | None:
    series = _coerce_numeric_series(params.get(field))
    if not series:
        return None
    return series[0]


def _should_apply_severe_harmonized_mismatch_reinvestment_floor(
    *,
    signal: _ConsensusAnchorSignal,
    shares_path: Mapping[str, object] | None,
    reinvestment_clamp_profile: ReinvestmentClampProfileLoadResult,
) -> bool:
    if not _is_shares_scope_mismatch_detected(shares_path):
        return False
    if not isinstance(shares_path, Mapping):
        return False
    resolution_raw = shares_path.get("scope_policy_resolution")
    if resolution_raw != "harmonized_market_class":
        return False
    mismatch_ratio = _coerce_float(shares_path.get("scope_mismatch_ratio"))
    if (
        mismatch_ratio is None
        or mismatch_ratio
        < reinvestment_clamp_profile.profile.dcf_growth.severe_scope_mismatch_ratio_threshold
    ):
        return False
    if signal.target_premium > DCF_GROWTH_LOW_PREMIUM_REINVESTMENT_PREMIUM_THRESHOLD:
        return False
    if signal.fallback_reason is None and signal.quality_bucket != "degraded":
        return False
    return True


def _supports_dcf_standard_consensus_relaxation(
    signal: _ConsensusAnchorSignal | None,
) -> bool:
    if signal is None:
        return False
    if signal.confidence < DCF_STANDARD_RELAX_MIN_CONFIDENCE:
        return False
    return True


def _resolve_dcf_standard_growth_guardrail_config(
    *,
    config: GrowthGuardrailConfig,
    market_snapshot: Mapping[str, object] | None,
) -> tuple[GrowthGuardrailConfig, str | None]:
    signal = _resolve_consensus_anchor_signal(market_snapshot=market_snapshot)
    if not _supports_dcf_standard_consensus_relaxation(signal):
        return config, None
    assert signal is not None
    if signal.target_premium <= DCF_STANDARD_GROWTH_RELAX_PREMIUM_TRIGGER:
        return config, None

    premium_signal = _clamp(
        signal.target_premium - DCF_STANDARD_GROWTH_RELAX_PREMIUM_TRIGGER,
        0.0,
        DCF_STANDARD_GROWTH_RELAX_PREMIUM_CAP,
    )
    relax_delta = min(
        DCF_STANDARD_GROWTH_RELAX_MAX,
        premium_signal * DCF_STANDARD_GROWTH_RELAX_SLOPE * signal.confidence,
    )
    if relax_delta <= 0:
        return config, None

    adjusted_max_year1 = min(
        config.max_series_growth,
        config.max_year1_growth + relax_delta,
    )
    adjusted_max_series = min(
        DCF_STANDARD_GROWTH_RELAX_MAX_SERIES_CAP,
        config.max_series_growth + relax_delta,
    )
    adjusted_max_terminal = min(
        0.055,
        config.max_terminal_growth + (relax_delta * 0.30),
    )

    if (
        adjusted_max_year1 <= config.max_year1_growth
        and adjusted_max_series <= config.max_series_growth
        and adjusted_max_terminal <= config.max_terminal_growth
    ):
        return config, None

    adjusted_config = GrowthGuardrailConfig(
        max_year1_growth=adjusted_max_year1,
        max_series_growth=adjusted_max_series,
        min_series_growth=config.min_series_growth,
        min_terminal_growth=config.min_terminal_growth,
        max_terminal_growth=adjusted_max_terminal,
        final_fade_years=config.final_fade_years,
        enforce_nonincreasing_trend=config.enforce_nonincreasing_trend,
    )
    return (
        adjusted_config,
        "dcf_standard_growth_consensus_relaxation applied "
        f"(premium={signal.target_premium:.2%}, confidence={signal.confidence:.2f}, "
        f"max_year1_raw={config.max_year1_growth:.4f}, "
        f"max_year1_adjusted={adjusted_max_year1:.4f}, "
        f"max_series_raw={config.max_series_growth:.4f}, "
        f"max_series_adjusted={adjusted_max_series:.4f}, "
        f"max_terminal_raw={config.max_terminal_growth:.4f}, "
        f"max_terminal_adjusted={adjusted_max_terminal:.4f}, "
        f"target_consensus_applied={signal.target_consensus_applied}, "
        f"source_count={signal.source_count}, "
        f"fallback_reason={signal.fallback_reason or 'none'}, "
        f"quality_bucket={signal.quality_bucket or 'unknown'})",
    )


def _resolve_dcf_standard_margin_guardrail_config(
    *,
    config: MarginGuardrailConfig,
    params: Mapping[str, object],
    market_snapshot: Mapping[str, object] | None,
) -> tuple[MarginGuardrailConfig, str | None]:
    growth_rates = _coerce_numeric_series(params.get("growth_rates"))
    year1_growth = growth_rates[0] if growth_rates else None
    if (
        isinstance(year1_growth, float)
        and year1_growth > DCF_STANDARD_MARGIN_RELAX_MAX_YEAR1_GROWTH
    ):
        return (
            config,
            "dcf_standard_margin_consensus_relaxation skipped "
            f"(year1_growth={year1_growth:.4f} > "
            f"threshold={DCF_STANDARD_MARGIN_RELAX_MAX_YEAR1_GROWTH:.4f})",
        )

    signal = _resolve_consensus_anchor_signal(market_snapshot=market_snapshot)
    if not _supports_dcf_standard_consensus_relaxation(signal):
        return config, None
    assert signal is not None
    if signal.target_premium <= DCF_STANDARD_MARGIN_RELAX_PREMIUM_TRIGGER:
        return config, None

    premium_signal = _clamp(
        signal.target_premium - DCF_STANDARD_MARGIN_RELAX_PREMIUM_TRIGGER,
        0.0,
        DCF_STANDARD_MARGIN_RELAX_PREMIUM_CAP,
    )
    relax_delta = min(
        DCF_STANDARD_MARGIN_RELAX_MAX,
        premium_signal * DCF_STANDARD_MARGIN_RELAX_SLOPE * signal.confidence,
    )
    if relax_delta <= 0:
        return config, None

    adjusted_upper = min(
        config.max_series_margin,
        config.normalized_margin_upper + relax_delta,
    )
    if adjusted_upper <= config.normalized_margin_upper:
        return config, None

    adjusted_config = MarginGuardrailConfig(
        min_series_margin=config.min_series_margin,
        max_series_margin=config.max_series_margin,
        normalized_margin_lower=config.normalized_margin_lower,
        normalized_margin_upper=adjusted_upper,
        final_fade_years=config.final_fade_years,
    )
    return (
        adjusted_config,
        "dcf_standard_margin_consensus_relaxation applied "
        f"(premium={signal.target_premium:.2%}, confidence={signal.confidence:.2f}, "
        f"normalized_upper_raw={config.normalized_margin_upper:.4f}, "
        f"normalized_upper_adjusted={adjusted_upper:.4f}, "
        f"target_consensus_applied={signal.target_consensus_applied}, "
        f"source_count={signal.source_count}, "
        f"fallback_reason={signal.fallback_reason or 'none'}, "
        f"quality_bucket={signal.quality_bucket or 'unknown'})",
    )


def _resolve_dcf_standard_capex_guardrail_config(
    *,
    config: ReinvestmentGuardrailConfig,
    market_snapshot: Mapping[str, object] | None,
) -> tuple[ReinvestmentGuardrailConfig, str | None]:
    signal = _resolve_consensus_anchor_signal(market_snapshot=market_snapshot)
    if not _supports_dcf_standard_consensus_relaxation(signal):
        return config, None
    assert signal is not None
    if signal.target_premium <= DCF_STANDARD_CAPEX_RELAX_PREMIUM_TRIGGER:
        return config, None

    premium_signal = _clamp(
        signal.target_premium - DCF_STANDARD_CAPEX_RELAX_PREMIUM_TRIGGER,
        0.0,
        DCF_STANDARD_CAPEX_RELAX_PREMIUM_CAP,
    )
    relax_delta = min(
        DCF_STANDARD_CAPEX_RELAX_MAX,
        premium_signal * DCF_STANDARD_CAPEX_RELAX_SLOPE * signal.confidence,
    )
    if relax_delta <= 0:
        return config, None

    adjusted_upper = max(
        config.terminal_lower + 0.005,
        config.terminal_upper - relax_delta,
    )
    if adjusted_upper >= config.terminal_upper:
        return config, None

    adjusted_config = ReinvestmentGuardrailConfig(
        min_series_rate=config.min_series_rate,
        max_series_rate=config.max_series_rate,
        terminal_lower=config.terminal_lower,
        terminal_upper=adjusted_upper,
        final_fade_years=config.final_fade_years,
    )
    return (
        adjusted_config,
        "dcf_standard_capex_consensus_relaxation applied "
        f"(premium={signal.target_premium:.2%}, confidence={signal.confidence:.2f}, "
        f"terminal_upper_raw={config.terminal_upper:.4f}, "
        f"terminal_upper_adjusted={adjusted_upper:.4f}, "
        f"target_consensus_applied={signal.target_consensus_applied}, "
        f"source_count={signal.source_count}, "
        f"fallback_reason={signal.fallback_reason or 'none'}, "
        f"quality_bucket={signal.quality_bucket or 'unknown'})",
    )


def _resolve_dcf_standard_wc_guardrail_config(
    *,
    config: ReinvestmentGuardrailConfig,
    market_snapshot: Mapping[str, object] | None,
) -> tuple[ReinvestmentGuardrailConfig, str | None]:
    signal = _resolve_consensus_anchor_signal(market_snapshot=market_snapshot)
    if not _supports_dcf_standard_consensus_relaxation(signal):
        return config, None
    assert signal is not None
    if signal.target_premium <= DCF_STANDARD_WC_RELAX_PREMIUM_TRIGGER:
        return config, None

    premium_signal = _clamp(
        signal.target_premium - DCF_STANDARD_WC_RELAX_PREMIUM_TRIGGER,
        0.0,
        DCF_STANDARD_WC_RELAX_PREMIUM_CAP,
    )
    relax_delta = min(
        DCF_STANDARD_WC_RELAX_MAX,
        premium_signal * DCF_STANDARD_WC_RELAX_SLOPE * signal.confidence,
    )
    if relax_delta <= 0:
        return config, None

    adjusted_lower = min(
        config.terminal_upper - 0.005,
        config.terminal_lower - relax_delta,
    )
    if adjusted_lower >= config.terminal_lower:
        return config, None

    adjusted_config = ReinvestmentGuardrailConfig(
        min_series_rate=config.min_series_rate,
        max_series_rate=config.max_series_rate,
        terminal_lower=adjusted_lower,
        terminal_upper=config.terminal_upper,
        final_fade_years=config.final_fade_years,
    )
    return (
        adjusted_config,
        "dcf_standard_wc_consensus_relaxation applied "
        f"(premium={signal.target_premium:.2%}, confidence={signal.confidence:.2f}, "
        f"terminal_lower_raw={config.terminal_lower:.4f}, "
        f"terminal_lower_adjusted={adjusted_lower:.4f}, "
        f"target_consensus_applied={signal.target_consensus_applied}, "
        f"source_count={signal.source_count}, "
        f"fallback_reason={signal.fallback_reason or 'none'}, "
        f"quality_bucket={signal.quality_bucket or 'unknown'})",
    )


def _resolve_shares_scope_policy_mode() -> str:
    raw = os.getenv(DCF_SHARES_SCOPE_POLICY_ENV)
    if raw is None:
        return DCF_SHARES_SCOPE_POLICY_HARMONIZE
    token = raw.strip().lower()
    if token in {
        DCF_SHARES_SCOPE_POLICY_HARMONIZE,
        DCF_SHARES_SCOPE_POLICY_CONSERVATIVE_ONLY,
    }:
        return token
    return DCF_SHARES_SCOPE_POLICY_HARMONIZE


def _normalize_shares_source(shares_source: str) -> str:
    token = shares_source
    if token.endswith("_dilution_proxy"):
        token = token.removesuffix("_dilution_proxy")
    return token


def _apply_variant_shares_scope_policy(
    *,
    params: dict[str, object],
    assumptions: list[str],
    trace_inputs: dict[str, object],
    shares_source: str,
    shares_path: dict[str, object] | None,
) -> tuple[str, dict[str, object] | None]:
    mode = _resolve_shares_scope_policy_mode()
    shares_path_payload: dict[str, object] = dict(shares_path or {})
    shares_path_payload["scope_policy_mode"] = mode

    mismatch_detected_raw = shares_path_payload.get("scope_mismatch_detected")
    mismatch_detected = (
        bool(mismatch_detected_raw)
        if isinstance(mismatch_detected_raw, bool)
        else False
    )
    market_shares = _coerce_float(shares_path_payload.get("market_shares"))
    filing_shares = _coerce_float(shares_path_payload.get("filing_shares"))
    mismatch_ratio = _coerce_float(shares_path_payload.get("scope_mismatch_ratio"))
    current_price = _coerce_float(params.get("current_price"))
    selected_shares_before = _coerce_float(params.get("shares_outstanding"))
    normalized_source = _normalize_shares_source(shares_source)
    market_is_stale = normalized_source.endswith("_market_stale_fallback")

    if mode == DCF_SHARES_SCOPE_POLICY_CONSERVATIVE_ONLY:
        shares_path_payload["scope_policy_resolution"] = "conservative_only"
        return shares_source, shares_path_payload

    if not mismatch_detected:
        shares_path_payload["scope_policy_resolution"] = "not_required"
        return shares_source, shares_path_payload

    if market_is_stale:
        shares_path_payload["scope_policy_resolution"] = (
            "market_stale_conservative_fallback"
        )
        assumptions.append(
            "dcf_shares_scope_policy mismatch detected but market shares stale; "
            "kept conservative filing denominator"
        )
        return shares_source, shares_path_payload

    if (
        market_shares is None
        or market_shares <= 0
        or current_price is None
        or current_price <= 0
    ):
        shares_path_payload["scope_policy_resolution"] = (
            "market_unavailable_conservative_fallback"
        )
        assumptions.append(
            "dcf_shares_scope_policy mismatch detected but market shares unavailable; "
            "kept conservative filing denominator"
        )
        return shares_source, shares_path_payload

    params["shares_outstanding"] = market_shares
    trace_inputs["shares_outstanding"] = TraceableField(
        name="Shares Outstanding (DCF Shares Scope Harmonized)",
        value=market_shares,
        provenance=ManualProvenance(
            description=(
                "Shares denominator harmonized to market-class scope for price/shares "
                "consistency under scope mismatch policy"
            ),
            author="ValuationPolicy",
        ),
    )
    assumptions.append(
        "dcf_shares_scope_policy harmonized denominator to market-class shares "
        f"(market={market_shares:.0f}, filing={filing_shares if filing_shares is not None else 'unknown'}, "
        f"mismatch_ratio={mismatch_ratio if mismatch_ratio is not None else 'unknown'})"
    )

    shares_path_payload["scope_policy_resolution"] = "harmonized_market_class"
    shares_path_payload["selected_source"] = "market_data_scope_harmonized"
    shares_path_payload["shares_scope"] = "market_class_harmonized"
    shares_path_payload["equity_value_scope"] = "market_class_harmonized"
    shares_path_payload["selected_shares"] = market_shares
    if selected_shares_before is not None:
        shares_path_payload["selected_shares_before_policy"] = selected_shares_before
    shares_path_payload["scope_mismatch_detected"] = True
    shares_path_payload["scope_mismatch_resolved"] = True
    return "market_data_scope_harmonized", shares_path_payload
