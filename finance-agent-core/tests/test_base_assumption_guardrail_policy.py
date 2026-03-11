from __future__ import annotations

import pytest

from src.agents.fundamental.subdomains.core_valuation.domain.policies.base_assumption_guardrail_policy import (
    DEFAULT_BASE_ASSUMPTION_GUARDRAIL_VERSION,
    ReinvestmentGuardrailConfig,
    apply_base_assumption_guardrail,
    apply_growth_guardrail,
    apply_margin_guardrail,
    apply_reinvestment_guardrail,
)


def test_apply_growth_guardrail_caps_hot_year1_and_fades_terminal() -> None:
    growth_rates = [0.80, 0.75, 0.70, 0.66, 0.62, 0.58, 0.53, 0.49, 0.44, 0.40]

    result = apply_growth_guardrail(
        growth_rates=growth_rates,
        long_run_growth_target=0.014,
    )

    assert result.hit is True
    assert result.guarded_series[0] == pytest.approx(0.55)
    assert result.guarded_series[-1] == pytest.approx(0.014)
    assert result.guarded_series[-4] >= result.guarded_series[-3]
    assert result.guarded_series[-3] >= result.guarded_series[-2]
    assert result.guarded_series[-2] >= result.guarded_series[-1]


def test_apply_growth_guardrail_enforces_nonincreasing_trend() -> None:
    growth_rates = [0.70, 0.80, 0.65, 0.60, 0.55, 0.50, 0.45, 0.30, 0.18, 0.14]

    result = apply_growth_guardrail(
        growth_rates=growth_rates,
        long_run_growth_target=0.014,
    )

    assert result.hit is True
    assert result.guarded_series[1] <= result.guarded_series[0]
    assert "growth_nonincreasing_trend_enforced" in result.reasons


def test_apply_margin_guardrail_converges_terminal_to_internal_band() -> None:
    operating_margins = [0.5943] * 10

    result = apply_margin_guardrail(operating_margins=operating_margins)

    assert result.hit is True
    assert result.guarded_series[-1] == pytest.approx(0.42)
    assert result.guarded_series[-3] > result.guarded_series[-2]
    assert result.guarded_series[-2] > result.guarded_series[-1]
    assert max(result.guarded_series) <= 0.70


def test_apply_base_assumption_guardrail_returns_combined_result() -> None:
    result = apply_base_assumption_guardrail(
        growth_rates=[0.68, 0.62, 0.57, 0.50, 0.44, 0.39, 0.33, 0.27, 0.22, 0.18],
        operating_margins=[0.5943] * 10,
        long_run_growth_target=0.014,
    )

    assert result.version == DEFAULT_BASE_ASSUMPTION_GUARDRAIL_VERSION
    assert result.guardrail_hit is True
    assert result.growth.hit is True
    assert result.margin.hit is True
    assert result.growth.guarded_series[-1] == pytest.approx(0.014)
    assert result.margin.guarded_series[-1] == pytest.approx(0.42)


def test_apply_growth_guardrail_raises_on_empty_input() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        apply_growth_guardrail(growth_rates=[], long_run_growth_target=0.014)


def test_apply_reinvestment_guardrail_uses_historical_anchor_when_available() -> None:
    result = apply_reinvestment_guardrail(
        series_rates=[0.42] * 10,
        config=ReinvestmentGuardrailConfig(
            min_series_rate=0.00,
            max_series_rate=0.32,
            terminal_lower=0.04,
            terminal_upper=0.16,
            final_fade_years=6,
        ),
        metric_prefix="capex",
        historical_anchor=0.20,
    )

    assert result.hit is True
    assert result.guarded_series[0] == pytest.approx(0.32)
    assert result.guarded_series[-1] == pytest.approx(0.16)
    assert "capex_series_clamped_to_bounds" in result.reasons
    assert "capex_anchor_clamped_to_terminal_band" in result.reasons
    assert "capex_terminal_converged_to_historical_anchor" in result.reasons


def test_apply_reinvestment_guardrail_raises_on_empty_series() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        apply_reinvestment_guardrail(
            series_rates=[],
            config=ReinvestmentGuardrailConfig(
                min_series_rate=0.0,
                max_series_rate=0.2,
                terminal_lower=0.02,
                terminal_upper=0.08,
                final_fade_years=4,
            ),
            metric_prefix="wc",
        )
