from datetime import UTC, datetime
from decimal import Decimal, localcontext

import pytest

from fundamental_service.calculator import CalculationRefusal, calculate
from fundamental_service.contracts import ScenarioInputV1, UncertaintyV1
from fundamental_service.forecast_timeline import build_forecast_timeline
from fundamental_service.policies import executable_model_specs, initial_model_specs
from fundamental_service.serialization import sha256_digest
from fundamental_service.testsupport import make_valuation
from fundamental_service.uncertainty import MonteCarloRequestV1, run_uncertainty
from fundamental_service.verification import independent_calculate
from test_forecast_timeline import revenue_history


def dated_request(model_id="fcff_dcf"):
    request = make_valuation()
    timestamp = datetime(2026, 11, 23, tzinfo=UTC)
    facts = revenue_history()
    forecast = request.assumptions.forecast.model_copy(
        update={
            "base_revenue": facts[-1].value,
            "revenue_growth": (Decimal("0.05"),) * 5,
            "operating_margin": (Decimal("0.15"),) * 5,
            "reinvestment_rate": (Decimal("0.20"),) * 5,
            "timeline": build_forecast_timeline(
                facts, valuation_timestamp=timestamp, horizon=5
            ),
        }
    )
    return request.model_copy(
        update={
            "model_id": model_id,
            "model_version": f"{model_id}-v3",
            "valuation_context": request.valuation_context.model_copy(
                update={"valuation_timestamp": timestamp}
            ),
            "historical_facts": (
                *[fact.fact_id for fact in facts],
                "filed_operating_evidence",
            ),
            "assumptions": request.assumptions.model_copy(
                update={"forecast": forecast}
            ),
        }
    ).with_digest()


@pytest.mark.parametrize("model_id", ["fcff_dcf", "transition_fcff_dcf"])
def test_dated_cash_flows_match_independent_equations_and_calendar_challenger(model_id):
    request = dated_request(model_id)
    result = calculate(request)
    reference = independent_calculate(request)
    assert result.calculation_version == "calculator-v3-dated-fcff"
    assert result.intrinsic_value == reference.intrinsic_value
    assert {node.node_id: node.value for node in result.nodes} == {
        node.node_id: node.value for node in reference.nodes
    }
    nodes = {node.node_id: node.value for node in result.nodes}
    first = request.assumptions.forecast.timeline.periods[0]
    with localcontext() as context:
        context.prec = 80
        included = (
            nodes["fcff_1"]
            * Decimal(first.included_days)
            / Decimal(first.full_period_days)
        )
        discount = (
            (Decimal(1) + nodes["wacc"]).ln()
            * Decimal(first.discount_days)
            / Decimal(365)
        )
        expected = included * (-discount).exp()
        assert abs(expected - nodes["discounted_fcff_1"]) < abs(expected) * Decimal(
            "1e-45"
        )
    assert nodes["included_fcff_1"] < nodes["fcff_1"]
    assert nodes["included_fcff_2"] == nodes["fcff_2"]
    assert result == calculate(request)


def test_old_model_is_unchanged_and_model_timeline_mismatch_refuses():
    baseline = make_valuation().with_digest()
    old = calculate(baseline)
    assert old.calculation_version == "calculator-v2"
    assert not any(node.node_id.startswith("included_fcff") for node in old.nodes)
    assert baseline.model_dump()["assumptions"]["forecast"].get("timeline") is None
    assert sha256_digest(initial_model_specs()) == sha256_digest(
        executable_model_specs()[:2]
    )
    request = dated_request()
    for forged in (
        request.model_copy(update={"model_version": "fcff_dcf-v2"}).with_digest(),
        baseline.model_copy(update={"model_version": "fcff_dcf-v3"}).with_digest(),
    ):
        with pytest.raises(CalculationRefusal) as error:
            calculate(forged)
        assert error.value.code == "FORECAST_TIMING_POLICY_MISMATCH"


def test_monte_carlo_scenarios_and_growth_change_keep_the_same_saved_timeline():
    request = dated_request()
    original = request.assumptions.forecast.timeline
    controls = MonteCarloRequestV1(
        uncertainty=UncertaintyV1(
            mode="monte_carlo",
            samples=8,
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
    mc = run_uncertainty(request, monte_carlo=controls)
    assert mc.valid_samples == 8
    assert mc.base.assumptions.forecast.timeline == original
    scenario_request = request.model_copy(
        update={
            "uncertainty": UncertaintyV1(
                mode="scenarios",
                scenarios=(
                    ScenarioInputV1(name="base"),
                    ScenarioInputV1(name="downside"),
                    ScenarioInputV1(
                        name="upside",
                        assumptions={"assumptions.terminal_growth": "0.01"},
                    ),
                ),
            )
        }
    ).with_digest()
    scenarios = run_uncertainty(scenario_request)
    assert all(
        result.assumptions.forecast.timeline == original
        for result in scenarios.scenario_results
    )
    assert (
        scenarios.scenario_results[0].per_share_value
        != scenarios.scenario_results[2].per_share_value
    )


def test_service_fact_admission_rebuilds_timeline_from_retained_sources():
    from types import SimpleNamespace

    from fundamental_service.app import create_app
    from fundamental_service.operations import ServiceError
    from test_api import _SnapshotRepository

    request = dated_request()
    facts = revenue_history()
    repository = _SnapshotRepository()
    repository.snapshot.identity = request.identity.model_copy(
        update={"issuer_id": facts[0].issuer_id}
    )
    request = request.model_copy(
        update={"historical_facts": tuple(fact.fact_id for fact in facts)}
    ).with_digest()
    app = create_app(
        repository,
        fact_repository=SimpleNamespace(
            get={fact.fact_id: fact for fact in facts}.__getitem__
        ),
    )
    application = app.state.application
    application._verify_fact_references(request)
    forecast = request.assumptions.forecast
    for changed, code in (
        (
            forecast.model_copy(update={"base_revenue": Decimal(999)}),
            "FORECAST_BASE_REVENUE_MISMATCH",
        ),
        (
            forecast.model_copy(
                update={
                    "timeline": forecast.timeline.model_copy(
                        update={"source_revenue_fact_id": "forged"}
                    )
                }
            ),
            "FORECAST_TIMELINE_SOURCE_MISMATCH",
        ),
    ):
        forged = request.model_copy(
            update={
                "assumptions": request.assumptions.model_copy(
                    update={"forecast": changed}
                )
            }
        ).with_digest()
        with pytest.raises(ServiceError) as error:
            application._verify_fact_references(forged)
        assert error.value.code == code


def test_source_plan_uses_explicit_dated_pin_and_keeps_legacy_configuration_bytes():
    from fundamental_service.original_source_plan import (
        AutomaticSourcePlanConfigurationV1,
    )
    from test_original_source_plan import configuration

    old = configuration()
    assert "model_version" not in old.model_dump()
    assert old.resolved_model_version == "fcff_dcf-v2"
    current = AutomaticSourcePlanConfigurationV1.model_validate(
        {**old.model_dump(), "model_version": "fcff_dcf-v3"}
    )
    assert current.resolved_model_version == "fcff_dcf-v3"
    with pytest.raises(ValueError, match="exact supported model version"):
        AutomaticSourcePlanConfigurationV1.model_validate(
            {**old.model_dump(), "model_version": "transition_fcff_dcf-v3"}
        )


@pytest.mark.parametrize("model_id", ["fcff_dcf", "transition_fcff_dcf"])
def test_policy_validation_transport_retains_prepared_forecast_timeline(model_id):
    from fastapi.testclient import TestClient

    from fundamental_service.app import create_app
    from fundamental_service.policies import (
        PolicyRecordV1,
        PolicyRegistry,
        initial_policy_records,
    )
    from fundamental_service.testsupport import auth_headers, make_internal_envelope

    request = dated_request(model_id)
    policy_payload = initial_policy_records()[0].model_dump(exclude={"policy_digest"})
    policy_payload.update(
        policy_id=f"{model_id}-dated-transport-policy",
        model_id=model_id,
        model_version=request.model_version,
    )
    policy = PolicyRecordV1.model_validate(
        {**policy_payload, "policy_digest": sha256_digest(policy_payload)}
    )
    client = TestClient(
        create_app(
            policy_registry=PolicyRegistry(
                models=executable_model_specs(), policies=(policy,)
            )
        )
    )
    payload = request.model_dump(mode="json")
    payload["policy_id"] = policy.policy_id
    payload["input_digest"] = None
    response = client.post(
        "/v1/valuation/validate-with-policy",
        headers=auth_headers(),
        json=make_internal_envelope(payload),
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert (
        result["input"]["assumptions"]["forecast"]["timeline"]
        == payload["assumptions"]["forecast"]["timeline"]
    )
    assert (
        result["policy_resolution"]["precedence"]["assumptions.forecast.timeline"]
        == "caller"
    )
    assert result["quality_status"] == "unsupported"
    assert "MODEL_RELEASE_EVIDENCE_MISSING" in result["issue_codes"]
