from __future__ import annotations

import pytest

from src.agents.fundamental.domain.valuation.assumptions import (
    DEFAULT_LONG_RUN_GROWTH_TARGET,
    blend_growth_rate,
    project_growth_rate_series,
    resolve_growth_blend_weights,
)


def test_resolve_growth_blend_weights_uses_mature_profile_for_low_volatility() -> None:
    weights = resolve_growth_blend_weights(0.03)
    assert weights.profile == "mature_stable"
    assert weights.historical > weights.consensus


def test_blend_growth_rate_uses_context_aware_weights() -> None:
    result = blend_growth_rate(
        historical_growth=0.10,
        consensus_growth=0.20,
        historical_volatility=0.03,
    )
    assert result is not None
    assert result.weights.profile == "mature_stable"
    assert 0.10 < result.blended_growth < 0.20


def test_project_growth_rate_series_applies_mean_reversion_for_high_growth() -> None:
    series = project_growth_rate_series(base_growth=0.50, projection_years=5)
    assert len(series) == 5
    assert series[0] > series[-1]
    assert series[-1] == pytest.approx(DEFAULT_LONG_RUN_GROWTH_TARGET)
