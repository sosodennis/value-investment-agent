"""Automatic source bindings retain hypotheses and refusals without approving callers."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from fundamental_service.conditional_reinvestment_preparation import (
    ConditionalReinvestmentBindingV1,
    prepare_conditional_reinvestment,
)
from fundamental_service.contracts import CallerApprovalEnvelopeV1
from fundamental_service.data_releases import DataReleaseError
from fundamental_service.facts import (
    FilesystemCanonicalFactRepository,
    canonical_fact_digest,
)
from fundamental_service.original_source_plan import AutomaticSourcePlanConfigurationV1
from fundamental_service.serialization import canonical_bytes
from fundamental_service.valuation_requirements import (
    automatic_source_requirements_profile,
    conditional_reinvestment_requirements_profile,
    source_preparation_requirements_profile,
)
from test_conditional_capital_preparation import recipe as capital_recipe
from test_conditional_reinvestment_composer import _fixture as composer_fixture
from test_conditional_reinvestment_release import _fixture
from test_composite_source_preparation import _plan
from test_issuer_operating_release import inventory
from test_original_preparation import case, execute
from test_original_source_plan import (
    compiler_case,
    configuration,
    working_capital_recipe_template,
)
from test_preparation_runner import (
    VALUATION_TIME,
    _acquisition,
    _reader,
    _reviewed_candidate,
    _run,
    _runner,
)
from test_valuation_release_inputs import _client


def bind(fixture, *, recipe=None, facts=None):
    return prepare_conditional_reinvestment(
        recipe or fixture.recipe,
        fixture.facts if facts is None else facts,
        snapshot=fixture.snapshot,
        artifacts=fixture.artifacts,
    )


def test_binding_rechecks_document_and_sources_deterministically(tmp_path):
    fixture = _fixture(tmp_path)
    first = bind(fixture)
    assert first.policy == fixture.policy and not first.issue_codes
    assert bind(fixture, facts=fixture.facts[::-1]) == first
    assert first.assumption_document_ref == fixture.manifest.artifact_refs[0]
    before = inventory(fixture.artifacts.root)
    with ThreadPoolExecutor(max_workers=3) as pool:
        repeats = tuple(pool.map(lambda _: bind(fixture), range(3)))
    assert all(item == first for item in repeats)
    assert inventory(fixture.artifacts.root) == before


@pytest.mark.parametrize(
    "fault",
    [
        "missing_document",
        "wrong_document",
        "wrong_hash",
        "missing_core",
        "future",
        "conflict",
    ],
)
def test_binding_retains_source_and_document_refusals(tmp_path, fault):
    fixture = _fixture(tmp_path)
    recipe, facts = fixture.recipe, fixture.facts
    if fault == "missing_document":
        recipe = recipe.model_copy(
            update={"assumption_document_uri": "artifact://missing"}
        )
    elif fault == "wrong_document":
        recipe = recipe.model_copy(
            update={
                "limitations": (
                    "This is another hypothetical assumption which the retained document does not authorize.",
                )
            }
        )
    elif fault == "wrong_hash":
        recipe = recipe.model_copy(update={"assumption_document_digest": "f" * 64})
    elif fault == "missing_core":
        facts = tuple(f for f in facts if f.normalized_field != "income_tax_expense")
    else:
        target = next(f for f in facts if f.normalized_field == "revenue")
        if fault == "future":
            facts = tuple(
                f.model_copy(
                    update={
                        "available_at": fixture.snapshot.valuation_timestamp.replace(
                            year=2030
                        )
                    }
                )
                if f == target
                else f
                for f in facts
            )
        else:
            facts = (
                *facts,
                target.model_copy(
                    update={"fact_id": "conflict", "value": target.value + 1}
                ),
            )
    binding = bind(fixture, recipe=recipe, facts=facts)
    assert binding.policy is None and binding.issue_codes and binding.failure_reasons
    assert binding == bind(fixture, recipe=recipe, facts=facts[::-1])
    if fault == "missing_core":
        assert "income_tax_expense" in binding.missing_evidence


@pytest.mark.parametrize("capital", [False, True])
def test_registered_source_profile_preserves_observed_capital_and_unknown_history(
    capital,
):
    profile = source_preparation_requirements_profile(
        "fcff_dcf", conditional_capital=capital, conditional_reinvestment=True
    )
    assert profile == conditional_reinvestment_requirements_profile(
        "fcff_dcf", conditional_capital=capital
    )
    assert profile == automatic_source_requirements_profile("fcff_dcf", profile.digest)
    assert "cash_and_equivalents" in profile.required_fact_fields
    assert "capital_expenditure" not in profile.required_fact_fields
    assert "capital_expenditure" in profile.supporting_fact_fields
    assert profile.supported_history_threshold is None


def test_original_compiler_uses_deployment_recipe_without_caller_plan(
    tmp_path, monkeypatch
):
    fixture = _fixture(tmp_path / "policy")
    value = case(tmp_path / "original", monkeypatch)
    prepared, _ = execute(value)
    configured = configuration()
    recipe = fixture.recipe.model_copy(
        update={"mapping_version": configured.mapping_version}
    )
    configured = type(configured).model_validate(
        configured.model_dump() | {"conditional_reinvestment_recipe": recipe}
    )
    compiler, request = compiler_case(value, prepared, configured)
    evidence, publication = compiler.execute(request)
    assert publication.wrote and evidence.plan.conditional_reinvestment_recipe == recipe
    assert (
        evidence.plan.ingestions[0].requirements_digest
        == evidence.plan.requirements_profile.digest
    )
    assert "capital_expenditure" not in evidence.plan.ingestions[0].required_fields
    assert not compiler.execute(request)[1].wrote


@pytest.mark.parametrize("fault", ["mapping", "model", "version", "composite"])
def test_configuration_refuses_incompatible_forward_recipe(tmp_path, fault):
    fixture = _fixture(tmp_path)
    configured = configuration()
    recipe = fixture.recipe.model_dump() | {
        "mapping_version": configured.mapping_version
    }
    payload = configured.model_dump()
    if fault == "mapping":
        recipe["mapping_version"] = "another-mapping"
    elif fault == "model":
        recipe.update(
            model_id="transition_fcff_dcf", model_version="transition_fcff_dcf-v2"
        )
    elif fault == "version":
        recipe["model_version"] = "unsupported-v0"
    else:
        payload["working_capital_recipe_template"] = working_capital_recipe_template()
    with pytest.raises(ValueError):
        AutomaticSourcePlanConfigurationV1.model_validate(
            payload | {"conditional_reinvestment_recipe": recipe}
        )


def test_source_runner_binds_prepares_and_resumes_joint_forward_input(tmp_path):
    fixture = composer_fixture(tmp_path, sec_profile=True)
    plan = _plan(
        fixture,
        conditional_capital_recipe=capital_recipe(fixture.capital_policy),
        conditional_reinvestment_recipe=fixture.forward_policy.recipe,
    )
    fixture.application = _client(fixture).app.state.application
    fixture.state.active = None
    receipt = _run(_runner(fixture, acquisition=_acquisition(fixture)), plan)
    unreleased = _reader(fixture, receipt)
    assert unreleased.status == "release_required", unreleased.issue_codes
    ref = unreleased.conditional_reinvestment_binding_ref
    binding = ConditionalReinvestmentBindingV1.model_validate_json(
        fixture.artifacts.read(ref.artifact_id)
    )
    assert binding.policy == fixture.forward_policy
    assert ref.content_hash in receipt.artifact.dependency_hashes
    candidate, canary = _reviewed_candidate(fixture)
    prepared = _reader(
        fixture, _run(_runner(fixture, canary=canary), plan, candidate=candidate)
    )
    assert prepared.status == "approval_required", prepared.issue_codes
    assert prepared.conditional_reinvestment_binding_ref == ref
    # Synthetic approval exercises the boundary; it is not real caller acceptance.
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
    repeat = _run(_runner(fixture), plan, approval=approval)
    assert not repeat.wrote and repeat.artifact == calculated.artifact
    assert inventory(fixture.artifacts.root) == before


def test_optional_source_contracts_keep_existing_canonical_identity():
    configured = configuration()
    assert b"conditional_reinvestment_recipe" not in canonical_bytes(configured)


def test_source_runner_retains_document_failure_and_reuses_refusal(
    tmp_path, monkeypatch
):
    fixture = composer_fixture(tmp_path, sec_profile=True)
    plan = _plan(
        fixture,
        conditional_capital_recipe=capital_recipe(fixture.capital_policy),
        conditional_reinvestment_recipe=fixture.forward_policy.recipe,
    )
    fixture.application = _client(fixture).app.state.application
    fixture.state.active = None
    original_read = fixture.artifacts.read
    document_id = fixture.forward_policy.recipe.assumption_document_uri.removeprefix(
        "artifact://"
    )
    monkeypatch.setattr(
        fixture.artifacts,
        "read",
        lambda key: b"corrupt" if key == document_id else original_read(key),
    )
    runner = _runner(fixture, acquisition=_acquisition(fixture))
    first = _run(runner, plan)
    refused = _reader(fixture, first)
    assert refused.status == "blocked" and refused.calculation is None
    assert "DATA_RELEASE_REINVESTMENT_DOCUMENT_HASH_MISMATCH" in refused.issue_codes
    ref = refused.conditional_reinvestment_binding_ref
    bound = ConditionalReinvestmentBindingV1.model_validate_json(
        original_read(ref.artifact_id)
    )
    assert bound.policy is None and bound.failure_reasons == (
        "assumption bytes differ",
    )
    assert ref.content_hash in first.artifact.dependency_hashes
    repeat = _run(runner, plan)
    assert repeat.artifact == first.artifact and not repeat.wrote


def test_active_release_rechecks_assumption_bytes_before_reuse(tmp_path, monkeypatch):
    fixture = composer_fixture(tmp_path, sec_profile=True)
    plan = _plan(
        fixture,
        conditional_capital_recipe=capital_recipe(fixture.capital_policy),
        conditional_reinvestment_recipe=fixture.forward_policy.recipe,
    )
    candidate, canary = _reviewed_candidate(fixture)
    fixture.application = _client(fixture).app.state.application
    runner = _runner(fixture, canary=canary)
    first = _run(runner, plan, candidate=candidate)
    assert _reader(fixture, first).status == "approval_required"
    original_read = fixture.artifacts.read
    document_id = fixture.forward_policy.recipe.assumption_document_uri.removeprefix(
        "artifact://"
    )
    monkeypatch.setattr(
        fixture.artifacts,
        "read",
        lambda key: b"corrupt" if key == document_id else original_read(key),
    )
    with pytest.raises(DataReleaseError) as caught:
        _run(runner, plan)
    assert caught.value.code == "DATA_RELEASE_REINVESTMENT_DOCUMENT_HASH_MISMATCH"


@pytest.mark.parametrize("fault", ["conflict", "future", "capital_conflict"])
def test_runner_retains_candidate_snapshot_and_reason_on_selection_failure(
    tmp_path, fault
):
    fixture = composer_fixture(tmp_path, sec_profile=True)
    plan = _plan(
        fixture,
        conditional_capital_recipe=capital_recipe(fixture.capital_policy),
        conditional_reinvestment_recipe=fixture.forward_policy.recipe,
    )
    facts = fixture.facts.list()
    role = "cash_and_equivalents" if fault == "capital_conflict" else "revenue"
    mapping_ids = {m.decision_id for m in plan.ingestions[0].mappings}
    target = next(
        f
        for f in facts
        if f.normalized_field == role and f.mapping_decision_id in mapping_ids
    )
    if fault in {"conflict", "capital_conflict"}:
        facts = (
            *facts,
            target.model_copy(
                update={"fact_id": "conflicting-candidate", "value": target.value + 1}
            ),
        )
    else:
        facts = tuple(
            f.model_copy(
                update={
                    "available_at": fixture.snapshot.valuation_timestamp.replace(
                        year=2030
                    ),
                    "captured_at": fixture.snapshot.valuation_timestamp.replace(
                        year=2030
                    ),
                }
            )
            if f == target
            else f
            for f in facts
        )
    fixture.facts = FilesystemCanonicalFactRepository(tmp_path / "refused-facts")
    for fact in facts:
        fixture.facts.publish(fact)
    fixture.application = _client(fixture).app.state.application
    fixture.state.active = None
    runner = _runner(fixture, acquisition=_acquisition(fixture))
    first = _run(runner, plan)
    refused = _reader(fixture, first)
    assert refused.status == "blocked" and refused.calculation is None
    assert refused.snapshot_manifest_digest == fixture.snapshot.manifest_digest
    ref = refused.conditional_reinvestment_binding_ref
    binding = ConditionalReinvestmentBindingV1.model_validate_json(
        fixture.artifacts.read(ref.artifact_id)
    )
    assert binding.policy is None and binding.failure_reasons and binding.issue_codes
    assert binding.input_fact_digests == tuple(
        sorted(
            {
                canonical_fact_digest(f)
                for f in facts
                if f.mapping_decision_id in mapping_ids
            }
        )
    )
    before = inventory(fixture.artifacts.root)
    repeat = _run(runner, plan)
    assert not repeat.wrote and repeat.artifact == first.artifact
    assert inventory(fixture.artifacts.root) == before
