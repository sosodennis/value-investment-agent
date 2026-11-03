from decimal import Decimal

import pytest

from fundamental_service.contracts import UncertaintyV1
from fundamental_service.uncertainty import (
    MonteCarloRequestV1,
    SensitivityRequestV1,
    run_uncertainty,
)
from fundamental_service.testsupport import make_valuation


def test_seeded_monte_carlo_reproduces_and_sensitivity_is_explicit():
    request = make_valuation().with_digest()
    spec = MonteCarloRequestV1(
        uncertainty=UncertaintyV1(
            mode="monte_carlo",
            samples=10,
            seed=42,
            invalid_draw_policy="reject",
            parameters=(
                {
                    "path": "assumptions.terminal_growth",
                    "distribution": "uniform",
                    "lower": Decimal("0.01"),
                    "upper": Decimal("0.03"),
                },
            ),
        )
    )
    sensitivity = (
        SensitivityRequestV1(
            path="assumptions.terminal_growth",
            values=(Decimal("0.01"), Decimal("0.02")),
        ),
    )
    first = run_uncertainty(request, monte_carlo=spec, sensitivity=sensitivity)
    second = run_uncertainty(request, monte_carlo=spec, sensitivity=sensitivity)
    assert first.quantiles == second.quantiles
    assert first.valid_samples == 10
    assert (
        first.sensitivity["assumptions.terminal_growth"][0]
        != first.sensitivity["assumptions.terminal_growth"][1]
    )
    assert first.dominant_drivers == ("assumptions.terminal_growth",)


def test_monte_carlo_requires_complete_specification():
    with pytest.raises(ValueError):
        MonteCarloRequestV1(uncertainty={"mode": "scenarios"})


def test_invalid_paths_and_correlations_are_rejected():
    with pytest.raises(ValueError):
        UncertaintyV1(
            mode="monte_carlo",
            samples=4,
            seed=1,
            invalid_draw_policy="skip",
            parameters=(
                {
                    "path": "other.value",
                    "distribution": "uniform",
                    "lower": Decimal("0"),
                    "upper": Decimal("1"),
                },
            ),
        )
    with pytest.raises(ValueError):
        UncertaintyV1(
            mode="monte_carlo",
            samples=4,
            seed=1,
            invalid_draw_policy="skip",
            parameters=(
                {
                    "path": "assumptions.terminal_growth",
                    "distribution": "uniform",
                    "lower": Decimal("0"),
                    "upper": Decimal("1"),
                },
            ),
            correlations=(
                (
                    "assumptions.terminal_growth",
                    "assumptions.terminal_growth",
                    Decimal("0.5"),
                ),
            ),
        )
