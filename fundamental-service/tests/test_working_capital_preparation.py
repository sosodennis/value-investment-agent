"""Source plans bind facts after acquisition and retain deterministic refusals."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.contracts import CallerApprovalEnvelopeV1
from fundamental_service.automatic_source_mapping import AutomaticSecIngestionRequestV1
from fundamental_service.facts import FilesystemCanonicalFactRepository
from fundamental_service.preparation_runner import (
    AutomaticSourcePreparationPlanV1,
    SOURCE_PREPARATION_PLAN,
)
from fundamental_service.serialization import canonical_bytes
from fundamental_service.working_capital_preparation import (
    ValuationWorkingCapitalRecipeV1,
    WorkingCapitalBindingV1,
    bind_working_capital_recipe,
)
from test_composite_source_preparation import _plan
from test_automatic_source_mapping import source_case
from test_issuer_operating_release import inventory
from test_preparation_runner import (
    VALUATION_TIME,
    _acquisition,
    _reader,
    _reviewed_candidate,
    _run,
    _runner,
)
from test_valuation_release_inputs import _client, _valuation_fixture


def _recipe_plan(fixture):
    plan = _plan(fixture)
    policy = plan.valuation_working_capital_policy
    recipe = ValuationWorkingCapitalRecipeV1(
        **policy.model_dump(exclude={"protocol", "inputs"}),
        periods=tuple(
            item.model_dump(
                include={
                    "accession_number",
                    "period_end",
                    "asset_residual",
                    "liability_residual",
                    "perimeter_rationale",
                }
            )
            | {
                "exclusions": tuple(
                    exclusion.model_dump(
                        include={
                            "account_class",
                            "mapped_fact_role",
                            "state",
                            "rationale",
                        }
                    )
                    for exclusion in item.exclusions
                )
            }
            for item in policy.inputs
        ),
    )
    return type(plan)(
        **plan.model_dump(exclude={"valuation_working_capital_policy"}),
        valuation_working_capital_recipe=recipe,
    )


def test_recipe_acquires_then_binds_formal_inputs_and_reuses_numerical_result(tmp_path):
    fixture = _valuation_fixture(tmp_path, sec_profile=True)
    plan = _recipe_plan(fixture)
    assert b"fact_id" not in canonical_bytes(plan.valuation_working_capital_recipe)
    fixture.application = _client(fixture).app.state.application
    fixture.state.active = None
    acquired = _run(_runner(fixture, acquisition=_acquisition(fixture)), plan)
    unreleased = _reader(fixture, acquired)
    assert unreleased.status == "release_required"
    binding_ref = unreleased.working_capital_binding_ref
    binding = WorkingCapitalBindingV1.model_validate_json(
        fixture.artifacts.read(binding_ref.artifact_id)
    )
    assert not binding.missing_evidence
    assert binding.policy == fixture.manifest.valuation_working_capital_policy
    assert binding.digest == binding_ref.content_hash
    candidate, canary = _reviewed_candidate(fixture)
    prepared = _reader(
        fixture, _run(_runner(fixture, canary=canary), plan, candidate=candidate)
    )
    assert prepared.status == "approval_required"
    assert prepared.working_capital_binding_ref == binding_ref
    approval = CallerApprovalEnvelopeV1(
        input_digest=prepared.preparation.input.input_digest,
        decision="approved",
        caller_id="operator",
        decided_at=VALUATION_TIME,
    )
    calculated = _run(_runner(fixture), plan, approval=approval)
    result = _reader(fixture, calculated)
    assert result.calculation.base.per_share_value > 0
    assert result.calculation.base.quality_status.value == "provisional"
    assert (
        result.preparation.historical_metrics.working_capital_inputs
        == binding.policy.inputs
    )
    assert plan.requirements_profile.supported_history_threshold is None
    before = inventory(fixture.artifacts.root)
    repeated = _run(_runner(fixture), plan, approval=approval, correlation="reopened")
    assert repeated.artifact == calculated.artifact and not repeated.wrote
    assert inventory(fixture.artifacts.root) == before


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "ambiguous",
        "foreign_mapping",
        "future",
        "wrong_source",
        "amended",
    ],
)
def test_recipe_retains_invalid_binding_and_reuses_negative_report(tmp_path, change):
    fixture = _valuation_fixture(tmp_path, sec_profile=True)
    plan = _recipe_plan(fixture)
    repository = FilesystemCanonicalFactRepository(tmp_path / "changed-facts")
    target = "cash_and_short_term_investments-2021"
    for fact in fixture.facts.list():
        if fact.fact_id == target:
            if change == "missing":
                continue
            if change == "ambiguous":
                repository.publish(
                    fact.model_copy(update={"fact_id": "duplicate-cash"})
                )
            elif change == "foreign_mapping":
                fact = fact.model_copy(update={"mapping_decision_id": "foreign"})
            elif change == "future":
                fact = fact.model_copy(
                    update={
                        "available_at": datetime(2027, 1, 1, tzinfo=UTC),
                        "captured_at": datetime(2027, 1, 1, tzinfo=UTC),
                    }
                )
            elif change == "wrong_source":
                fact = fact.model_copy(
                    update={
                        "source": fact.source.model_copy(
                            update={"content_hash": "f" * 64}
                        )
                    }
                )
            elif change == "amended":
                fact = fact.model_copy(update={"is_amendment": True})
        repository.publish(fact)
    fixture.facts = repository
    fixture.application = _client(fixture).app.state.application
    fixture.state.active = None
    runner = _runner(fixture, acquisition=_acquisition(fixture))
    first = _run(runner, plan)
    evidence = _reader(fixture, first)
    assert evidence.status == "blocked" and evidence.calculation is None
    assert evidence.issue_codes == ("SOURCE_PREPARATION_WORKING_CAPITAL_INVALID",)
    report = WorkingCapitalBindingV1.model_validate_json(
        fixture.artifacts.read(evidence.working_capital_binding_ref.artifact_id)
    )
    assert (
        report.policy is None and report.missing_evidence == evidence.missing_evidence
    )
    expected = {
        "missing": "BINDING_MISSING",
        "ambiguous": "BINDING_AMBIGUOUS",
        "foreign_mapping": "BINDING_MISSING",
        "future": "AVAILABILITY",
        "wrong_source": "BINDING_MISSING",
        "amended": "AMENDMENT",
    }[change]
    assert any(expected in reason for reason in report.missing_evidence)
    before = inventory(fixture.artifacts.root)
    repeated = _run(runner, plan, correlation="repeat-refusal")
    assert repeated.artifact == first.artifact and not repeated.wrote
    assert inventory(fixture.artifacts.root) == before


def test_recipe_binding_is_independent_of_candidate_order_even_with_conflicting_ids(
    tmp_path,
):
    fixture = _valuation_fixture(tmp_path, sec_profile=True)
    recipe = _recipe_plan(fixture).valuation_working_capital_recipe
    facts = tuple(fixture.facts.list())
    target = next(fact for fact in facts if fact.fact_id == "current_assets-2021")
    conflicting = (
        *facts,
        target.model_copy(update={"value": target.value + Decimal(1)}),
    )
    first = bind_working_capital_recipe(recipe, conflicting, snapshot=fixture.snapshot)
    second = bind_working_capital_recipe(
        recipe, tuple(reversed(conflicting)), snapshot=fixture.snapshot
    )
    assert first.policy is None and first.digest == second.digest
    assert first == second
    assert (
        len([fact for fact in first.candidate_facts if fact.fact_id == target.fact_id])
        == 2
    )


@pytest.mark.parametrize(
    "pin",
    [
        "model_version",
        "requirements_profile_digest",
        "mapping_version",
        "accession_number",
        "both",
    ],
)
def test_recipe_rejects_foreign_pins_and_competing_policy(tmp_path, pin):
    fixture = _valuation_fixture(tmp_path, sec_profile=True)
    plan = _recipe_plan(fixture)
    payload = plan.model_dump()
    recipe = payload["valuation_working_capital_recipe"]
    if pin == "both":
        payload["valuation_working_capital_policy"] = (
            fixture.manifest.valuation_working_capital_policy
        )
    elif pin == "accession_number":
        recipe["periods"][0][pin] = "foreign-original"
    else:
        recipe[pin] = "f" * 64 if pin == "requirements_profile_digest" else "foreign"
    with pytest.raises(ValidationError):
        type(plan)(**payload)


def test_recipe_does_not_supply_unknown_exclusions_or_implicit_scenarios(tmp_path):
    fixture = _valuation_fixture(tmp_path, sec_profile=True)
    recipe = _recipe_plan(fixture).valuation_working_capital_recipe
    payload = recipe.model_dump()
    payload["periods"][0]["exclusions"] = payload["periods"][0]["exclusions"][:-1]
    with pytest.raises(ValidationError, match="cover each required class"):
        type(recipe)(**payload)
    payload = recipe.model_dump()
    for side in ("asset_residual", "liability_residual"):
        scenario = payload["periods"][0][side]
        scenario["low"] = scenario["high"] = scenario["central"]
    with pytest.raises(ValidationError, match="explicit sensitivity"):
        type(recipe)(**payload)


def test_candidate_must_match_the_reconstructed_recipe_before_any_writes(tmp_path):
    fixture = _valuation_fixture(tmp_path, sec_profile=True)
    plan = _recipe_plan(fixture)
    payload = plan.model_dump()
    payload["valuation_working_capital_recipe"]["periods"][0]["asset_residual"][
        "central"
    ] = Decimal("0.7")
    changed = type(plan)(**payload)
    candidate, canary = _reviewed_candidate(fixture)
    fixture.application = _client(fixture).app.state.application
    before = inventory(fixture.artifacts.root)
    with pytest.raises(ValueError, match="candidate does not match"):
        _run(_runner(fixture, canary=canary), changed, candidate=candidate)
    assert inventory(fixture.artifacts.root) == before


@pytest.mark.parametrize("mapping", ["exact", "foreign"])
def test_automatic_mapping_free_recipe_plan_uses_the_same_binding_contract(
    tmp_path, mapping
):
    fixture = _valuation_fixture(tmp_path / "valuation", sec_profile=True)
    manual = _recipe_plan(fixture)
    automatic, *_ = source_case(tmp_path / "automatic")
    payload = automatic.model_dump() | manual.ingestions[0].model_dump(
        exclude={"mappings"}
    )
    payload.update(
        source_revision=manual.source_revision,
        requirements_digest=manual.requirements_profile.digest,
        required_fields=manual.requirements_profile.required_fact_fields,
        mapping_version=manual.valuation_working_capital_recipe.mapping_version
        if mapping == "exact"
        else "foreign",
        supplemental_filing_policy=automatic.supplemental_filing_policy,
    )
    request = AutomaticSecIngestionRequestV1(**payload)
    if mapping == "foreign":
        with pytest.raises(ValidationError):
            AutomaticSourcePreparationPlanV1(
                **manual.model_dump(exclude={"protocol", "ingestions"}),
                ingestions=(request,),
            )
        return
    plan = AutomaticSourcePreparationPlanV1(
        **manual.model_dump(exclude={"protocol", "ingestions"}),
        ingestions=(request,),
    )
    assert SOURCE_PREPARATION_PLAN.validate_json(canonical_bytes(plan)) == plan
    assert "mappings" not in plan.ingestions[0].model_dump()
    assert plan.requirements_profile == manual.requirements_profile
