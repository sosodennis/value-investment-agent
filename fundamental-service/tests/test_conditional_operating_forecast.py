from decimal import Decimal, localcontext

import pytest

from fundamental_service.annual_history import resolve_annual_history
from fundamental_service.conditional_reinvestment import (
    ConditionalReinvestmentError,
    bind_conditional_reinvestment_recipe,
    reinvestment_history_requirements_profile,
)
from fundamental_service.conditional_reinvestment_contracts import REINVESTMENT_UNKNOWNS
from fundamental_service.contracts import QualityStatus
from fundamental_service.serialization import canonical_bytes
from fundamental_service.valuation_preparation import (
    PreparationError,
    compose_conditional_operating_forecasts,
    compose_forecast_assumptions,
    derive_historical_metrics,
)
from test_conditional_reinvestment import _case


def _operating_case():
    recipe, facts, snapshot = _case()
    amounts = {
        2023: ("100", "20", "16", "4"),
        2024: ("120", "24", "19.2", "4.8"),
        2025: ("144", "28.8", "23.04", "5.76"),
    }
    fields = ("revenue", "operating_income", "income_before_tax", "income_tax_expense")
    facts = tuple(
        fact.model_copy(
            update={
                "value": Decimal(
                    amounts[fact.period_end.year][fields.index(fact.normalized_field)]
                )
            }
        )
        for fact in facts
    )
    return recipe, facts, snapshot


def _compose(recipe, facts, snapshot):
    assessment = bind_conditional_reinvestment_recipe(recipe, facts, snapshot=snapshot)
    return compose_conditional_operating_forecasts(
        assessment.policy,
        facts,
        snapshot=snapshot,
        mapping_version=recipe.mapping_version,
    )


def test_forward_scenarios_use_shared_formulas_without_inventing_historical_fcff():
    recipe, facts, snapshot = _operating_case()
    original = canonical_bytes(facts)
    result = _compose(recipe, facts, snapshot)
    repeated = _compose(recipe, tuple(reversed(facts)), snapshot)
    assert result.input_digest == repeated.input_digest
    assert result.output_digest == repeated.output_digest
    assert canonical_bytes(facts) == original
    assert result.historical_metrics.quality_status is QualityStatus.PROVISIONAL
    assert set(result.historical_metrics.missing_evidence) == set(REINVESTMENT_UNKNOWNS)
    assert (
        "CONDITIONAL_FORWARD_REINVESTMENT_HYPOTHESES"
        in result.historical_metrics.issue_codes
    )
    assert {item.metric_id for item in result.historical_metrics.metrics} == {
        "operating_margin",
        "normalized_tax_rate",
        "nopat",
        "revenue_growth",
    }
    nopat = next(
        item
        for item in result.historical_metrics.metrics
        if item.metric_id == "nopat" and item.fiscal_year == 2025
    )
    assert nopat.value == Decimal("21.6")
    assert len(nopat.fact_ids) == 3
    assert [item.hypothesis.name for item in result.scenarios] == [
        "base",
        "downside",
        "upside",
    ]
    for scenario in result.scenarios:
        assert scenario.forecast.base_revenue == Decimal("144")
        assert scenario.forecast.revenue_growth == tuple(
            map(Decimal, (".2", ".16", ".12", ".08", ".04"))
        )
        assert scenario.forecast.operating_margin == (Decimal(".2"),) * 5
        assert (
            scenario.forecast.reinvestment_rate
            == (scenario.hypothesis.reinvestment_rate,) * 5
        )


def test_existing_history_route_still_requires_observed_reinvestment():
    recipe, facts, snapshot = _operating_case()
    history = resolve_annual_history(
        facts,
        snapshot=snapshot,
        valuation_timestamp=snapshot.valuation_timestamp,
        profile=reinvestment_history_requirements_profile(recipe.model_id),
    )
    exact_metrics = derive_historical_metrics(history)
    assert "METRIC_REQUIRED_FIELDS_MISSING" in exact_metrics.issue_codes
    with pytest.raises(PreparationError) as caught:
        compose_forecast_assumptions(history, exact_metrics)
    assert caught.value.code == "FORECAST_HISTORY_INSUFFICIENT"
    result = _compose(recipe, facts, snapshot)
    with pytest.raises(PreparationError) as caught:
        compose_forecast_assumptions(history, result.historical_metrics)
    assert caught.value.code == "FORECAST_HISTORY_INSUFFICIENT"


def test_forward_composition_replays_the_exact_policy_before_deriving_metrics():
    recipe, facts, snapshot = _operating_case()
    policy = bind_conditional_reinvestment_recipe(
        recipe, facts, snapshot=snapshot
    ).policy
    with pytest.raises(ConditionalReinvestmentError) as caught:
        compose_conditional_operating_forecasts(
            policy, facts, snapshot=snapshot, mapping_version="different-mapping"
        )
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_MAPPING_MISMATCH"
    changed = facts[-1].model_copy(update={"value": Decimal("7")})
    with pytest.raises(ConditionalReinvestmentError) as caught:
        compose_conditional_operating_forecasts(
            policy,
            (*facts[:-1], changed),
            snapshot=snapshot,
            mapping_version=recipe.mapping_version,
        )
    assert caught.value.code == "CONDITIONAL_REINVESTMENT_OBSERVATIONS_MISMATCH"


@pytest.mark.parametrize("field", ("revenue", "income_before_tax"))
def test_unstable_observed_denominators_refuse_forward_composition(field):
    recipe, facts, snapshot = _operating_case()
    facts = tuple(
        fact.model_copy(update={"value": Decimal(0)})
        if fact.normalized_field == field
        else fact
        for fact in facts
    )
    with pytest.raises(PreparationError) as caught:
        _compose(recipe, facts, snapshot)
    assert caught.value.code == "CONDITIONAL_OPERATING_METRICS_INVALID"


def test_forward_route_keeps_existing_growth_bounds():
    recipe, facts, snapshot = _operating_case()
    facts = tuple(
        fact.model_copy(update={"value": Decimal("10000")})
        if fact.normalized_field == "revenue" and fact.period_end.year == 2025
        else fact
        for fact in facts
    )
    with pytest.raises(PreparationError) as caught:
        _compose(recipe, facts, snapshot)
    assert caught.value.code == "FORECAST_GROWTH_OUT_OF_BOUNDS"


def test_forward_composition_is_independent_of_ambient_decimal_precision():
    recipe, facts, snapshot = _operating_case()
    expected = _compose(recipe, facts, snapshot)
    with localcontext() as context:
        context.prec = 4
        actual = _compose(recipe, facts, snapshot)
    assert actual.output_digest == expected.output_digest
