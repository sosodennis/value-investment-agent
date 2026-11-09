from decimal import Decimal

import pytest
from fundamental_service.contracts import (
    DistributionProvenanceV1,
    UncertaintyV1,
)
from fundamental_service.testsupport import make_valuation
from fundamental_service.uncertainty import (
    MonteCarloRequestV1,
    SensitivityRequestV1,
    run_uncertainty,
)
from fundamental_service.uncertainty_policy import build_default_uncertainty
from fundamental_service.valuation_preparation import HistoricalMetricV1


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


def test_distribution_provenance_requires_source_specific_evidence():
    with pytest.raises(ValueError, match="historical periods and source facts"):
        DistributionProvenanceV1(
            source_kind="empirical_history",
            estimation_method="mean",
            rationale="history",
        )
    with pytest.raises(ValueError, match="policy version"):
        DistributionProvenanceV1(
            source_kind="policy_prior",
            estimation_method="bounded_prior",
            rationale="approved prior",
        )


def test_versioned_monte_carlo_requires_parameter_provenance():
    with pytest.raises(ValueError, match="distribution provenance"):
        UncertaintyV1(
            mode="monte_carlo",
            policy_version="uncertainty-policy-v1",
            samples=4,
            seed=1,
            invalid_draw_policy="skip",
            parameters=(
                {
                    "path": "assumptions.terminal_growth",
                    "distribution": "uniform",
                    "lower": Decimal("0"),
                    "upper": Decimal("0.03"),
                },
            ),
        )


def test_default_policy_uses_empirical_history_and_policy_prior_with_stable_seed():
    request = make_valuation()
    metrics = tuple(
        HistoricalMetricV1(
            metric_id=metric_id,
            fiscal_year=year,
            value=Decimal(value),
            unit="ratio",
            formula="fixture",
            fact_ids=(f"{metric_id}-{year}",),
            period_end=f"{year}-12-31",
        )
        for metric_id, count in (
            ("revenue_growth", 3),
            ("operating_margin", 4),
            ("reinvestment_rate", 3),
        )
        for year, value in zip(
            range(2021, 2021 + count),
            ("0.03", "0.05", "0.07", "0.08"),
            strict=False,
        )
    )
    first = build_default_uncertainty(request, historical_metrics=metrics)
    second = build_default_uncertainty(request, historical_metrics=metrics)

    assert first == second
    assert first.samples == 256
    assert first.invalid_draw_policy == "skip"
    assert first.policy_version == "fcff-monte-carlo-policy-v1"
    assert first.seed is not None
    assert all(item.provenance is not None for item in first.parameters)
    assert [item.provenance.source_kind for item in first.parameters] == [
        "empirical_history",
        "empirical_history",
        "empirical_history",
        "policy_prior",
    ]
    assert first.parameters[0].provenance.historical_periods == (2021, 2022, 2023)


def test_default_policy_falls_back_to_explicit_prior_for_short_history():
    request = make_valuation()
    metrics = (
        HistoricalMetricV1(
            metric_id="revenue_growth",
            fiscal_year=2025,
            value=Decimal("0.05"),
            unit="ratio",
            formula="fixture",
            fact_ids=("revenue-growth-2025",),
            period_end="2025-12-31",
        ),
    )
    spec = build_default_uncertainty(request, historical_metrics=metrics)

    assert all(
        item.provenance.source_kind == "policy_prior" for item in spec.parameters
    )
    assert all(item.provenance.policy_version for item in spec.parameters)


def test_scenario_mode_rejects_missing_or_ignored_controls():
    request = (
        make_valuation()
        .model_copy(update={"uncertainty": UncertaintyV1(mode="scenarios")})
        .with_digest()
    )
    with pytest.raises(ValueError, match="requires scenario or sensitivity"):
        run_uncertainty(request)
    with pytest.raises(ValueError, match="cannot include Monte Carlo"):
        UncertaintyV1(
            mode="scenarios",
            scenarios=({"name": "base", "assumptions": {}},),
            samples=5,
            seed=7,
            invalid_draw_policy="skip",
            parameters=(
                {
                    "path": "assumptions.terminal_growth",
                    "distribution": "uniform",
                    "lower": Decimal("0.01"),
                    "upper": Decimal("0.03"),
                },
            ),
        )


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
