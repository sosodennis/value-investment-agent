"""Automatic capital bindings preserve observed facts and unknown hypotheses."""

from datetime import timedelta

import pytest

from fundamental_service.conditional_capital_contracts import (
    ConditionalCapitalRecipeV1,
    UNRESOLVED_CAPITAL_FIELDS,
)
from fundamental_service.conditional_capital_preparation import (
    ConditionalCapitalBindingV1,
    bind_conditional_capital_recipe,
)
from fundamental_service.contracts import CallerApprovalEnvelopeV1
from fundamental_service.award_disclosures import AWARD_DISCLOSURE_FIELDS
from fundamental_service.conditional_capital import (
    ConditionalCapitalError,
    assess_conditional_capital,
)
from fundamental_service.facts import FilesystemCanonicalFactRepository
from fundamental_service.original_source_plan import AutomaticSourcePlanConfigurationV1
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.valuation_requirements import (
    automatic_source_requirements_profile,
    source_preparation_requirements_profile,
)
from test_conditional_capital import _case
from test_conditional_capital_release import _conditional_fixture
from test_composite_source_preparation import _plan
from test_issuer_operating_release import inventory
from test_original_preparation import case, execute
from test_original_source_plan import compiler_case, configuration
from test_preparation_runner import (
    VALUATION_TIME,
    _acquisition,
    _reader,
    _reviewed_candidate,
    _run,
    _runner,
)
from test_valuation_release_inputs import _client, _manifest_with


def recipe(policy):
    return ConditionalCapitalRecipeV1(
        **policy.model_dump(
            include={
                "model_id",
                "model_version",
                "mapping_version",
                "max_quote_age_seconds",
                "limitations",
                "scenarios",
                "balance_hypotheses",
            }
        )
    )


def test_automatic_binding_retains_all_hypotheses_and_order_independent_digests():
    policy, facts, snapshot = _case()
    value = recipe(policy)
    first = bind_conditional_capital_recipe(value, facts, snapshot=snapshot)
    assert not first.issue_codes and first.policy == policy
    assert first.assessment.policy.complete_award_inventory is False
    assert len(first.assessment.scenarios) == 3
    assert first.input_fact_digests == tuple(sorted(sha256_digest(f) for f in facts))
    second = bind_conditional_capital_recipe(value, facts[::-1], snapshot=snapshot)
    assert canonical_bytes(first) == canonical_bytes(second)
    assert b"fact_id" not in canonical_bytes(value)


def test_aggregate_award_support_does_not_assert_complete_inventory_or_allocate_cost():
    policy, facts, snapshot = _case()
    instrument = next(f for f in facts if f.normalized_field == "equity_award_quantity")
    aggregates = tuple(
        instrument.model_copy(update={"fact_id": field, "normalized_field": field})
        for field in AWARD_DISCLOSURE_FIELDS
    )
    facts = (*tuple(f for f in facts if f != instrument), *aggregates)
    binding = bind_conditional_capital_recipe(recipe(policy), facts, snapshot=snapshot)
    assert not binding.issue_codes
    assert {ref.fact_id for ref in binding.policy.supporting_observations} == {
        fact.fact_id for fact in aggregates
    }
    assert binding.policy.complete_award_inventory is False
    assert {
        "complete_award_inventory",
        "compensation_allocation",
        "per_strike_inventory",
    } <= set(binding.policy.unknowns)
    # Supporting aggregates never change the explicit hypothetical share operands.
    assert binding.policy.scenarios == policy.scenarios
    assert binding == bind_conditional_capital_recipe(
        recipe(policy), facts[::-1], snapshot=snapshot
    )
    dropped = binding.policy.model_copy(
        update={"supporting_observations": binding.policy.supporting_observations[:1]}
    )
    with pytest.raises(ConditionalCapitalError) as error:
        assess_conditional_capital(
            dropped, facts, snapshot=snapshot, mapping_version=policy.mapping_version
        )
    assert error.value.code == "CONDITIONAL_CAPITAL_AWARD_OBSERVATIONS_UNBOUND"


@pytest.mark.parametrize(
    "failure",
    [
        "missing",
        "ambiguous",
        "future",
        "conflict",
        "source",
        "amended",
        "period",
        "awards",
    ],
)
def test_automatic_binding_retains_refusals(failure):
    policy, facts, snapshot = _case()
    target = next(f for f in facts if f.normalized_field == "cash_and_equivalents")
    expected = {
        "missing": "CONDITIONAL_CAPITAL_BINDING_MISSING",
        "ambiguous": "CONDITIONAL_CAPITAL_BINDING_AMBIGUOUS",
        "future": "CONDITIONAL_CAPITAL_SOURCE_INVALID",
        "conflict": "CONDITIONAL_CAPITAL_BINDING_AMBIGUOUS",
        "source": "CONDITIONAL_CAPITAL_SOURCE_INVALID",
        "amended": "CONDITIONAL_CAPITAL_SOURCE_INVALID",
        "period": "CONDITIONAL_CAPITAL_OBSERVATION_INVALID",
        "awards": "CONDITIONAL_CAPITAL_BINDING_MISSING",
    }[failure]
    if failure == "missing":
        facts = tuple(f for f in facts if f != target)
    elif failure in {"ambiguous", "conflict"}:
        copy = target.model_copy(
            update={
                "fact_id": "second-observation",
                "value": target.value + (1 if failure == "conflict" else 0),
            }
        )
        facts = (*facts, copy)
    elif failure == "awards":
        facts = tuple(f for f in facts if f.normalized_field != "equity_award_quantity")
    else:
        changes = {
            "future": {
                "available_at": snapshot.valuation_timestamp + timedelta(days=1)
            },
            "source": {
                "source": target.source.model_copy(update={"content_hash": "f" * 64})
            },
            "amended": {"is_amendment": True},
            "period": {"instant": target.instant - timedelta(days=1)},
        }[failure]
        facts = tuple(
            target.model_copy(update=changes) if f == target else f for f in facts
        )
    first = bind_conditional_capital_recipe(recipe(policy), facts, snapshot=snapshot)
    assert first.policy is None and expected in first.issue_codes
    assert first == bind_conditional_capital_recipe(
        recipe(policy), facts[::-1], snapshot=snapshot
    )


@pytest.mark.parametrize("composite", [False, True])
def test_conditional_source_profile_keeps_observed_roles_required(composite):
    legacy = source_preparation_requirements_profile(
        "fcff_dcf", composite_inputs=composite
    )
    profile = source_preparation_requirements_profile(
        "fcff_dcf", composite_inputs=composite, conditional_capital=True
    )
    assert set(profile.required_fact_fields) == set(legacy.required_fact_fields) - set(
        UNRESOLVED_CAPITAL_FIELDS
    )
    assert set(UNRESOLVED_CAPITAL_FIELDS) <= set(profile.supporting_fact_fields)
    assert set(AWARD_DISCLOSURE_FIELDS) <= set(profile.supporting_fact_fields)
    assert not set(AWARD_DISCLOSURE_FIELDS) & set(legacy.supporting_fact_fields)
    assert profile.profile_id != legacy.profile_id
    assert automatic_source_requirements_profile("fcff_dcf", profile.digest) == profile
    assert profile.supported_history_threshold is None


@pytest.mark.parametrize("with_balances", [False, True])
def test_saved_original_compiler_carries_deployment_recipe_without_fact_ids(
    tmp_path, monkeypatch, with_balances
):
    from test_conditional_capital_balances import balance_hypotheses

    value = case(tmp_path, monkeypatch)
    prepared, _ = execute(value)
    policy, _, _ = _case()
    configured = configuration()
    capital = recipe(policy).model_copy(
        update={
            "mapping_version": configured.mapping_version,
            "balance_hypotheses": balance_hypotheses() if with_balances else None,
        }
    )
    configured = type(configured).model_validate(
        configured.model_dump() | {"conditional_capital_recipe": capital}
    )
    compiler, request = compiler_case(value, prepared, configured)
    first, publication = compiler.execute(request)
    assert publication.wrote and first.plan.conditional_capital_recipe == capital
    assert (
        first.plan.ingestions[0].requirements_digest
        == first.plan.requirements_profile.digest
    )
    assert not {*UNRESOLVED_CAPITAL_FIELDS, *capital.hypothetical_balance_fields} & set(
        first.plan.ingestions[0].required_fields
    )
    assert not compiler.execute(request)[1].wrote


@pytest.mark.parametrize("change", ["version", "mapping", "model", "sensitivity"])
def test_deployment_configuration_rejects_invalid_capital_recipe(change):
    policy, _, _ = _case()
    configured = configuration()
    payload = recipe(policy).model_dump() | {
        "mapping_version": configured.mapping_version
    }
    if change == "version":
        payload["model_version"] = "unsupported-v0"
    elif change == "mapping":
        payload["mapping_version"] = "another-mapping"
    elif change == "model":
        payload.update(
            model_id="transition_fcff_dcf", model_version="transition_fcff_dcf-v2"
        )
    else:
        payload["scenarios"] = tuple(
            scenario.model_copy(update={"preferred_claims": 0})
            for scenario in policy.scenarios
        )
    with pytest.raises(ValueError):
        AutomaticSourcePlanConfigurationV1.model_validate(
            configured.model_dump() | {"conditional_capital_recipe": payload}
        )


def test_source_runner_binds_releases_prepares_and_resumes_approved_conditional_input(
    tmp_path,
):
    fixture = _conditional_fixture(tmp_path, sec_profile=True)
    capital = recipe(fixture.capital_policy)
    plan = _plan(fixture, conditional_capital_recipe=capital)
    fixture.application = _client(fixture).app.state.application
    fixture.state.active = None
    acquired = _run(_runner(fixture, acquisition=_acquisition(fixture)), plan)
    unreleased = _reader(fixture, acquired)
    assert unreleased.status == "release_required"
    ref = unreleased.conditional_capital_binding_ref
    binding = ConditionalCapitalBindingV1.model_validate_json(
        fixture.artifacts.read(ref.artifact_id)
    )
    assert binding.policy == fixture.capital_policy
    assert ref.content_hash in acquired.artifact.dependency_hashes
    candidate, canary = _reviewed_candidate(fixture)
    prepared = _reader(
        fixture, _run(_runner(fixture, canary=canary), plan, candidate=candidate)
    )
    assert prepared.status == "approval_required"
    assert prepared.conditional_capital_binding_ref == ref
    approval = CallerApprovalEnvelopeV1(
        input_digest=prepared.preparation.input.input_digest,
        decision="approved",
        caller_id="operator",
        decided_at=VALUATION_TIME,
    )
    calculated = _run(_runner(fixture), plan, approval=approval)
    result = _reader(fixture, calculated)
    assert result.calculation.base.per_share_value is not None
    assert len(result.calculation.scenario_results) == 3
    before = inventory(fixture.artifacts.root)
    repeated = _run(_runner(fixture), plan, approval=approval)
    assert not repeated.wrote and repeated.artifact == calculated.artifact
    assert inventory(fixture.artifacts.root) == before


def test_source_runner_rejects_release_with_different_bound_hypotheses(tmp_path):
    fixture = _conditional_fixture(tmp_path, sec_profile=True)
    plan = _plan(fixture, conditional_capital_recipe=recipe(fixture.capital_policy))
    different = fixture.capital_policy.model_copy(update={"max_quote_age_seconds": 10})
    fixture.manifest = _manifest_with(
        fixture.manifest, conditional_capital_policies=(different,)
    )
    candidate, canary = _reviewed_candidate(fixture)
    fixture.application = _client(fixture).app.state.application
    with pytest.raises(ValueError, match="candidate does not match"):
        _run(_runner(fixture, canary=canary), plan, candidate=candidate)


def test_source_runner_retains_missing_observation_and_reuses_blocked_binding(tmp_path):
    fixture = _conditional_fixture(tmp_path, sec_profile=True)
    plan = _plan(fixture, conditional_capital_recipe=recipe(fixture.capital_policy))
    repository = FilesystemCanonicalFactRepository(tmp_path / "missing-capital")
    for fact in fixture.facts.list():
        if fact.normalized_field != "cash_and_equivalents":
            repository.publish(fact)
    fixture.facts = repository
    fixture.application = _client(fixture).app.state.application
    fixture.state.active = None
    runner = _runner(fixture, acquisition=_acquisition(fixture))
    first = _run(runner, plan)
    report = _reader(fixture, first)
    assert (
        report.status == "blocked" and report.preparation is report.calculation is None
    )
    assert "CONDITIONAL_CAPITAL_BINDING_MISSING" in report.issue_codes
    assert "cash_and_equivalents" in report.missing_evidence
    ref = report.conditional_capital_binding_ref
    binding = ConditionalCapitalBindingV1.model_validate_json(
        fixture.artifacts.read(ref.artifact_id)
    )
    assert binding.policy is None
    assert binding.issue_codes == report.issue_codes
    before = inventory(fixture.artifacts.root)
    assert not _run(runner, plan).wrote
    assert inventory(fixture.artifacts.root) == before


def test_source_runner_resumes_after_interrupted_capital_binding_publication(
    tmp_path, monkeypatch
):
    fixture = _conditional_fixture(tmp_path, sec_profile=True)
    plan = _plan(fixture, conditional_capital_recipe=recipe(fixture.capital_policy))
    fixture.application = _client(fixture).app.state.application
    fixture.state.active = None
    runner = _runner(fixture, acquisition=_acquisition(fixture))
    delegate = fixture.artifacts.put_with_receipt
    interrupted = False

    def publish(artifact_id, *args, **kwargs):
        nonlocal interrupted
        if artifact_id.startswith("conditional-capital-binding:") and not interrupted:
            interrupted = True
            raise OSError("simulated interruption")
        return delegate(artifact_id, *args, **kwargs)

    monkeypatch.setattr(fixture.artifacts, "put_with_receipt", publish)
    with pytest.raises(OSError, match="simulated interruption"):
        _run(runner, plan)
    first = _run(runner, plan)
    assert _reader(fixture, first).status == "release_required"
    before = inventory(fixture.artifacts.root)
    assert not _run(runner, plan).wrote
    assert inventory(fixture.artifacts.root) == before


def test_conditional_candidate_resumes_when_its_snapshot_must_be_acquired(tmp_path):
    fixture = _conditional_fixture(tmp_path, sec_profile=True)
    plan = _plan(fixture, conditional_capital_recipe=recipe(fixture.capital_policy))
    fixture.application = _client(fixture).app.state.application
    fixture.state.active = None
    candidate, canary = _reviewed_candidate(fixture)
    (
        tmp_path / "conditional-snapshots" / f"{fixture.snapshot.snapshot_id}.json"
    ).unlink()
    acquisition = _acquisition(fixture)
    runner = _runner(fixture, acquisition=acquisition, canary=canary)
    first = _run(runner, plan, candidate=candidate)
    assert len(acquisition.calls) == 1 and fixture.state.publications == 1
    assert _reader(fixture, first).status == "approval_required"
    assert not _run(runner, plan).wrote


def test_candidate_static_compatibility_cannot_replace_post_acquisition_binding(
    tmp_path,
):
    fixture = _conditional_fixture(tmp_path, sec_profile=True)
    plan = _plan(fixture, conditional_capital_recipe=recipe(fixture.capital_policy))
    fixture.application = _client(fixture).app.state.application
    fixture.state.active = None
    candidate, canary = _reviewed_candidate(fixture)
    repository = FilesystemCanonicalFactRepository(tmp_path / "changed-capital")
    for fact in fixture.facts.list():
        if fact.normalized_field != "cash_and_equivalents":
            repository.publish(fact)
    fixture.facts = repository
    fixture.application = _client(fixture).app.state.application
    (
        tmp_path / "conditional-snapshots" / f"{fixture.snapshot.snapshot_id}.json"
    ).unlink()
    acquisition = _acquisition(fixture)
    runner = _runner(fixture, acquisition=acquisition, canary=canary)
    runner.validate_candidate(plan, candidate)
    publication = _run(runner, plan, candidate=candidate)
    report = _reader(fixture, publication)
    assert report.status == "blocked"
    assert "CONDITIONAL_CAPITAL_BINDING_MISSING" in report.issue_codes
    assert fixture.state.publications == 0 and fixture.state.active is None
