from decimal import Decimal

import pytest
from fundamental_service.contracts import (
    DistributionProvenanceV1,
    QualityStatus,
    UncertaintyV1,
    ScenarioInputV1,
)
from fundamental_service.calculator import calculate
from fundamental_service.testsupport import make_valuation
from fundamental_service.uncertainty import (
    MonteCarloRequestV1,
    SensitivityRequestV1,
    run_uncertainty,
    validate_uncertainty_controls,
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
    assert first.result_hash == second.result_hash
    assert first.valid_samples == 10
    assert (
        first.sensitivity["assumptions.terminal_growth"][0]
        != first.sensitivity["assumptions.terminal_growth"][1]
    )
    assert first.dominant_drivers == ("assumptions.terminal_growth",)


def test_joint_capital_scenarios_match_the_existing_calculator_and_replay():
    request = make_valuation()
    prefix = "assumptions.capital_bridge."
    controls = UncertaintyV1(
        mode="scenarios",
        scenarios=(
            ScenarioInputV1(name="base"),
            ScenarioInputV1(
                name="downside",
                assumptions={
                    prefix + "debt": "30",
                    prefix + "preferred_stock": "10",
                    prefix + "diluted_shares": "100",
                },
            ),
            ScenarioInputV1(
                name="upside",
                assumptions={
                    prefix + "debt": "5",
                    prefix + "preferred_stock": "0",
                    prefix + "diluted_shares": "125",
                },
            ),
        ),
        sensitivity=(
            SensitivityRequestV1(path=prefix + "preferred_stock", values=("0", "10")),
            SensitivityRequestV1(path=prefix + "diluted_shares", values=("100", "125")),
        ),
    )
    request = request.model_copy(update={"uncertainty": controls}).with_digest()
    original = request.model_dump()

    first = run_uncertainty(request)
    second = run_uncertainty(request)

    assert request.model_dump() == original
    assert first == second
    assert first.input_digest == request.input_digest
    for scenario, actual in zip(
        controls.scenarios, first.scenario_results, strict=True
    ):
        payload = make_valuation().model_dump()
        for path, value in scenario.assumptions.items():
            payload["assumptions"]["capital_bridge"][path.removeprefix(prefix)] = (
                Decimal(value)
            )
        expected = calculate(type(request).model_validate(payload).with_digest())
        assert actual.result_hash == expected.result_hash
        assert actual.per_share_value == expected.per_share_value
        assert actual.nodes[:-2] == first.base.nodes[:-2]
    assert (
        first.sensitivity[prefix + "preferred_stock"][0]
        > first.sensitivity[prefix + "preferred_stock"][1]
    )
    assert (
        first.sensitivity[prefix + "diluted_shares"][0]
        > first.sensitivity[prefix + "diluted_shares"][1]
    )


@pytest.mark.parametrize(
    "field",
    (
        "cash",
        "non_operating_assets",
        "debt",
        "preferred_stock",
        "lease_liabilities",
        "non_controlling_interest",
        "diluted_shares",
    ),
)
def test_capital_sensitivity_changes_only_the_declared_operand(field):
    request = make_valuation()
    path = f"assumptions.capital_bridge.{field}"
    report = run_uncertainty(
        request,
        sensitivity=(SensitivityRequestV1(path=path, values=("20", "40")),),
    )
    expected = []
    for value in (Decimal("20"), Decimal("40")):
        payload = request.model_dump()
        payload["assumptions"]["capital_bridge"][field] = value
        expected.append(
            calculate(type(request).model_validate(payload)).per_share_value
        )
    assert report.sensitivity[path] == tuple(expected)


def test_joint_weight_changes_validate_once_after_the_complete_scenario():
    request = make_valuation()
    joint = {
        "assumptions.wacc.debt_weight": "0.4",
        "assumptions.wacc.equity_weight": "0.6",
    }
    scenarios = tuple(
        ScenarioInputV1(name=name, assumptions=joint)
        for name in ("base", "downside", "upside")
    )
    report = run_uncertainty(request, scenarios=scenarios)
    assert all(
        item.assumptions.wacc.debt_weight == Decimal("0.4")
        for item in report.scenario_results
    )
    invalid = (
        scenarios[0].model_copy(update={"assumptions": {next(iter(joint)): "0.4"}}),
        *scenarios[1:],
    )
    with pytest.raises(ValueError, match="sum to 1"):
        run_uncertainty(request, scenarios=invalid)


def test_coupled_monte_carlo_operands_validate_as_one_draw():
    request = make_valuation()
    controls = MonteCarloRequestV1(
        uncertainty=UncertaintyV1(
            mode="monte_carlo",
            samples=10,
            seed=42,
            invalid_draw_policy="reject",
            parameters=tuple(
                {
                    "path": f"assumptions.wacc.{field}",
                    "distribution": "uniform",
                    "lower": Decimal(value),
                    "upper": Decimal(value),
                }
                for field, value in (("debt_weight", "0.4"), ("equity_weight", "0.6"))
            ),
        )
    )
    report = run_uncertainty(request, monte_carlo=controls)
    payload = request.model_dump()
    payload["assumptions"]["wacc"].update(
        debt_weight=Decimal("0.4"), equity_weight=Decimal("0.6")
    )
    expected = calculate(type(request).model_validate(payload)).per_share_value
    assert report.valid_samples == 10
    assert report.invalid_samples == 0
    assert report.quantiles["p05"] == report.quantiles["p95"] == expected


@pytest.mark.parametrize(
    "value", ("NaN", "Infinity", "-Infinity", "not a number", None, {}, True)
)
def test_non_numeric_or_nonfinite_capital_controls_are_refused_before_execution(value):
    with pytest.raises(ValueError, match="finite number"):
        validate_uncertainty_controls(
            make_valuation(),
            sensitivity=(
                SensitivityRequestV1(
                    path="assumptions.capital_bridge.debt", values=("0", value)
                ),
            ),
        )


@pytest.mark.parametrize(
    "field,value", (("debt", "-1"), ("diluted_shares", "-1"), ("diluted_shares", "0"))
)
def test_invalid_capital_operands_are_refused(field, value):
    with pytest.raises(ValueError):
        run_uncertainty(
            make_valuation(),
            sensitivity=(
                SensitivityRequestV1(
                    path=f"assumptions.capital_bridge.{field}", values=("1", value)
                ),
            ),
        )


@pytest.mark.parametrize(
    "path",
    (
        "assumptions.capital_bridge.model_config",
        "assumptions.capital_bridge.debt.amount",
        "assumptions.wacc.model_config",
        "assumptions.forecast.revenue_growth[-1]",
        "assumptions.forecast.revenue_growth[00]",
        "assumptions.forecast.revenue_growth[100]",
        "assumptions.trace.description",
        "quality.status",
    ),
)
def test_unknown_or_noncanonical_sensitivity_paths_are_refused(path):
    with pytest.raises(ValueError, match="unsupported assumption path"):
        run_uncertainty(
            make_valuation(),
            sensitivity=(SensitivityRequestV1(path=path, values=("1", "2")),),
        )


def test_duplicate_scenario_names_and_sensitivity_paths_are_refused():
    scenarios = tuple(
        ScenarioInputV1(name=name) for name in ("base", "downside", "upside", "base")
    )
    with pytest.raises(ValueError, match="exactly once"):
        run_uncertainty(make_valuation(), scenarios=scenarios)
    sensitivity = SensitivityRequestV1(
        path="assumptions.capital_bridge.debt", values=("0", "1")
    )
    with pytest.raises(ValueError, match="paths must be unique"):
        run_uncertainty(make_valuation(), sensitivity=(sensitivity, sensitivity))


def test_capital_scenarios_preserve_provisional_quality():
    request = make_valuation()
    request = request.model_copy(
        update={
            "quality": request.quality.model_copy(
                update={"status": QualityStatus.PROVISIONAL}
            )
        }
    )
    report = run_uncertainty(
        request,
        sensitivity=(
            SensitivityRequestV1(
                path="assumptions.capital_bridge.debt", values=("0", "1")
            ),
        ),
        allow_provisional=True,
    )
    assert report.status is QualityStatus.PROVISIONAL
    assert report.base.quality_status is QualityStatus.PROVISIONAL


def test_invalid_draws_are_accounted_for_and_abstain_explicitly():
    request = make_valuation().with_digest()
    spec = MonteCarloRequestV1(
        uncertainty=UncertaintyV1(
            mode="monte_carlo",
            samples=5,
            seed=1,
            invalid_draw_policy="abstain",
            parameters=(
                {
                    "path": "assumptions.terminal_growth",
                    "distribution": "uniform",
                    "lower": Decimal("0.08"),
                    "upper": Decimal("0.20"),
                },
            ),
        )
    )

    report = run_uncertainty(request, monte_carlo=spec)

    assert report.status is QualityStatus.ABSTAIN
    assert report.valid_samples + report.invalid_samples == report.requested_samples
    assert report.invalid_samples == 5
    assert report.invalid_reasons == {"CALCULATION_REFUSAL": 5}


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
