from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_BASE_ASSUMPTION_GUARDRAIL_VERSION = "base_assumption_guardrail_v1_2026_03_05"


@dataclass(frozen=True)
class GrowthGuardrailConfig:
    max_year1_growth: float = 0.55
    max_series_growth: float = 0.85
    min_series_growth: float = -0.50
    min_terminal_growth: float = -0.01
    max_terminal_growth: float = 0.05
    final_fade_years: int = 3
    enforce_nonincreasing_trend: bool = True


@dataclass(frozen=True)
class MarginGuardrailConfig:
    min_series_margin: float = -0.25
    max_series_margin: float = 0.70
    normalized_margin_lower: float = 0.18
    normalized_margin_upper: float = 0.42
    final_fade_years: int = 3


@dataclass(frozen=True)
class ReinvestmentGuardrailConfig:
    min_series_rate: float
    max_series_rate: float
    terminal_lower: float
    terminal_upper: float
    final_fade_years: int


@dataclass(frozen=True)
class BaseAssumptionGuardrailConfig:
    version: str = DEFAULT_BASE_ASSUMPTION_GUARDRAIL_VERSION
    growth: GrowthGuardrailConfig = field(default_factory=GrowthGuardrailConfig)
    margin: MarginGuardrailConfig = field(default_factory=MarginGuardrailConfig)


@dataclass(frozen=True)
class GuardrailedSeries:
    raw_series: tuple[float, ...]
    guarded_series: tuple[float, ...]
    hit: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ReinvestmentGuardrailResult:
    raw_series: tuple[float, ...]
    guarded_series: tuple[float, ...]
    hit: bool
    reasons: tuple[str, ...]
    terminal_target: float
    historical_anchor: float | None


@dataclass(frozen=True)
class BaseAssumptionGuardrailResult:
    growth: GuardrailedSeries
    margin: GuardrailedSeries
    version: str

    @property
    def guardrail_hit(self) -> bool:
        return self.growth.hit or self.margin.hit


DEFAULT_BASE_ASSUMPTION_GUARDRAIL_CONFIG = BaseAssumptionGuardrailConfig()


def apply_base_assumption_guardrail(
    *,
    growth_rates: list[float],
    operating_margins: list[float],
    long_run_growth_target: float,
    config: BaseAssumptionGuardrailConfig | None = None,
) -> BaseAssumptionGuardrailResult:
    resolved = config or DEFAULT_BASE_ASSUMPTION_GUARDRAIL_CONFIG
    growth = apply_growth_guardrail(
        growth_rates=growth_rates,
        long_run_growth_target=long_run_growth_target,
        config=resolved.growth,
    )
    margin = apply_margin_guardrail(
        operating_margins=operating_margins,
        config=resolved.margin,
    )
    return BaseAssumptionGuardrailResult(
        growth=growth,
        margin=margin,
        version=resolved.version,
    )


def apply_growth_guardrail(
    *,
    growth_rates: list[float],
    long_run_growth_target: float,
    config: GrowthGuardrailConfig | None = None,
) -> GuardrailedSeries:
    if len(growth_rates) == 0:
        raise ValueError("growth_rates cannot be empty")

    resolved = config or GrowthGuardrailConfig()
    reasons: list[str] = []

    raw_series = tuple(float(value) for value in growth_rates)
    guarded = list(raw_series)
    guarded = [
        _clamp(value, resolved.min_series_growth, resolved.max_series_growth)
        for value in guarded
    ]
    if tuple(guarded) != raw_series:
        reasons.append("growth_series_clamped_to_bounds")

    if guarded[0] > resolved.max_year1_growth:
        guarded[0] = resolved.max_year1_growth
        reasons.append("growth_year1_capped")
    if resolved.enforce_nonincreasing_trend:
        guarded, trend_enforced = _enforce_nonincreasing_trend(guarded)
        if trend_enforced:
            reasons.append("growth_nonincreasing_trend_enforced")

    terminal_target = _clamp(
        long_run_growth_target,
        resolved.min_terminal_growth,
        resolved.max_terminal_growth,
    )
    if guarded[-1] != terminal_target:
        reasons.append("growth_terminal_aligned_to_long_run_target")
    guarded = _apply_linear_terminal_fade(
        series=guarded,
        terminal_target=terminal_target,
        final_fade_years=resolved.final_fade_years,
    )
    guarded[-1] = terminal_target

    guarded_series = tuple(guarded)
    return GuardrailedSeries(
        raw_series=raw_series,
        guarded_series=guarded_series,
        hit=raw_series != guarded_series,
        reasons=tuple(reasons),
    )


def apply_margin_guardrail(
    *,
    operating_margins: list[float],
    config: MarginGuardrailConfig | None = None,
) -> GuardrailedSeries:
    if len(operating_margins) == 0:
        raise ValueError("operating_margins cannot be empty")

    resolved = config or MarginGuardrailConfig()
    reasons: list[str] = []

    raw_series = tuple(float(value) for value in operating_margins)
    guarded = list(raw_series)
    guarded = [
        _clamp(value, resolved.min_series_margin, resolved.max_series_margin)
        for value in guarded
    ]
    if tuple(guarded) != raw_series:
        reasons.append("margin_series_clamped_to_bounds")

    terminal_target = _clamp(
        guarded[-1],
        resolved.normalized_margin_lower,
        resolved.normalized_margin_upper,
    )
    if guarded[-1] != terminal_target:
        reasons.append("margin_terminal_converged_to_normalized_band")
    guarded = _apply_linear_terminal_fade(
        series=guarded,
        terminal_target=terminal_target,
        final_fade_years=resolved.final_fade_years,
    )
    guarded[-1] = terminal_target

    guarded_series = tuple(guarded)
    return GuardrailedSeries(
        raw_series=raw_series,
        guarded_series=guarded_series,
        hit=raw_series != guarded_series,
        reasons=tuple(reasons),
    )


def apply_reinvestment_guardrail(
    *,
    series_rates: list[float],
    config: ReinvestmentGuardrailConfig,
    metric_prefix: str,
    historical_anchor: float | None = None,
) -> ReinvestmentGuardrailResult:
    if len(series_rates) == 0:
        raise ValueError("series_rates cannot be empty")
    if not metric_prefix:
        raise ValueError("metric_prefix cannot be empty")

    reasons: list[str] = []
    raw_series = tuple(float(value) for value in series_rates)
    guarded = [
        _clamp(value, config.min_series_rate, config.max_series_rate)
        for value in raw_series
    ]
    if tuple(guarded) != raw_series:
        reasons.append(f"{metric_prefix}_series_clamped_to_bounds")

    terminal_target: float
    if historical_anchor is None:
        terminal_target = _clamp(
            guarded[-1],
            config.terminal_lower,
            config.terminal_upper,
        )
        if guarded[-1] != terminal_target:
            reasons.append(f"{metric_prefix}_terminal_converged_to_internal_band")
    else:
        clamped_anchor = _clamp(
            historical_anchor,
            config.terminal_lower,
            config.terminal_upper,
        )
        if clamped_anchor != historical_anchor:
            reasons.append(f"{metric_prefix}_anchor_clamped_to_terminal_band")
        terminal_target = clamped_anchor
        if guarded[-1] != terminal_target:
            reasons.append(f"{metric_prefix}_terminal_converged_to_historical_anchor")

    guarded = _apply_linear_terminal_fade(
        series=guarded,
        terminal_target=terminal_target,
        final_fade_years=config.final_fade_years,
    )
    guarded[-1] = terminal_target

    guarded_series = tuple(guarded)
    return ReinvestmentGuardrailResult(
        raw_series=raw_series,
        guarded_series=guarded_series,
        hit=raw_series != guarded_series,
        reasons=tuple(reasons),
        terminal_target=terminal_target,
        historical_anchor=historical_anchor,
    )


def _apply_linear_terminal_fade(
    *,
    series: list[float],
    terminal_target: float,
    final_fade_years: int,
) -> list[float]:
    output = list(series)
    if len(output) <= 1 or final_fade_years <= 0:
        return output

    start_index = max(0, len(output) - final_fade_years - 1)
    start_value = output[start_index]
    steps = len(output) - start_index - 1
    if steps <= 0:
        return output

    for step in range(1, steps + 1):
        ratio = float(step) / float(steps)
        output[start_index + step] = (start_value * (1.0 - ratio)) + (
            terminal_target * ratio
        )
    return output


def _enforce_nonincreasing_trend(series: list[float]) -> tuple[list[float], bool]:
    output = list(series)
    changed = False
    for idx in range(1, len(output)):
        if output[idx] <= output[idx - 1]:
            continue
        output[idx] = output[idx - 1]
        changed = True
    return output, changed


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
